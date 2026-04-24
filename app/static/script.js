function addEntityRequirementRow(courseId = null, sessionsRequired = 1) {
  if (!els.entityRequirementRows) return;
  const clone = els.requirementRowTemplate.content.firstElementChild.cloneNode(true);
  const courseInput = clone.querySelector('.requirement-course');
  const datalist = clone.querySelector('datalist#courseOptions');
  // Populate datalist with courses
  datalist.innerHTML = '';
  (state.data.courses || []).forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.name;
    datalist.appendChild(opt);
  });
  if (courseId) courseInput.value = String(courseId);
  clone.querySelector('.requirement-count').value = sessionsRequired;
  clone.querySelector('.remove-row-btn').addEventListener('click', () => clone.remove());
  els.entityRequirementRows.appendChild(clone);
}

// ...existing code...

// Fetches the latest data and updates the UI
async function refreshData(timetableId = null) {
  try {
    let url = '/api/bootstrap';
    if (timetableId) {
      url += `?timetable_id=${timetableId}`;
    }
    const res = await fetch(url);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      alert('Failed to load data: ' + (data.detail || res.statusText));
      return;
    }
    const data = await res.json();
    state.data = data;
    if (data.selected_timetable_id) {
      state.timetableId = data.selected_timetable_id;
    }
    state.selected = [];
    renderContextSelectors();
    renderEntityLists();
    renderBoard();
    renderTeacherLoad();
    populateStaticInputs();
    renderRequirementsSection();
    checkExportAllowed();
  } catch (err) {
    alert('Error loading data: ' + err);
  }
}

function renderRequirementsSection() {
  const root = document.getElementById('requirementsList');
  if (!root) return;
  root.innerHTML = '';
  const groupTags = state.data.group_tags || [];
  const programs = state.data.programs || [];
  const groups = state.data.groups || [];

  const groupTagRequirements = [];
  groupTags.forEach(tag => {
    if (tag.requirements && tag.requirements.length) {
      tag.requirements.forEach(req => groupTagRequirements.push({ tag, req }));
    }
  });

  const programRequirements = [];
  programs.forEach(prog => {
    if (prog.requirements && prog.requirements.length) {
      prog.requirements.forEach(req => programRequirements.push({ prog, req }));
    }
  });

  const groupOnlyRequirements = [];
  groups.forEach(group => {
    (group.group_requirements || []).forEach(req => {
      groupOnlyRequirements.push({ group, req });
    });
  });

  if (groupOnlyRequirements.length) {
    groupOnlyRequirements.forEach(({ group, req }) => {
      const row = document.createElement('div');
      row.className = 'requirement-row';
      row.innerHTML = `<span><strong>Group:</strong> ${escapeHtml(group.code)} — ${escapeHtml(group.name)}</span><span>Course: ${escapeHtml(req.course_name || req.course_id)}</span><span>Sessions: ${req.sessions_required || 1}</span>`;
      const editBtn = document.createElement('button');
      editBtn.className = 'ghost-btn small';
      editBtn.textContent = 'Edit';
      editBtn.onclick = () => openEditGroupOnlyRequirementModal(req);
      const delBtn = document.createElement('button');
      delBtn.className = 'danger-btn small';
      delBtn.textContent = 'Delete';
      delBtn.onclick = () => deleteGroupOnlyRequirement(req.id);
      row.appendChild(editBtn);
      row.appendChild(delBtn);
      root.appendChild(row);
    });
  }

  if (groupTagRequirements.length) {
    groupTagRequirements.forEach(({ tag, req }) => {
      const row = document.createElement('div');
      row.className = 'requirement-row';
      row.innerHTML = `<span><strong>Group Tag:</strong> ${escapeHtml(tag.code)} — ${escapeHtml(tag.name)}</span><span>Course: ${escapeHtml(req.course_name || req.course_id)}</span><span>Sessions: ${req.sessions_required || 1}</span>`;
      const editBtn = document.createElement('button');
      editBtn.className = 'ghost-btn small';
      editBtn.textContent = 'Edit';
      editBtn.onclick = () => openEditRequirementModal('group_tag', tag.id, req.course_id, req.sessions_required);
      const delBtn = document.createElement('button');
      delBtn.className = 'danger-btn small';
      delBtn.textContent = 'Delete';
      delBtn.onclick = () => deleteRequirement('group_tag', tag.id, req.course_id);
      row.appendChild(editBtn);
      row.appendChild(delBtn);
      root.appendChild(row);
    });
  }

  if (programRequirements.length) {
    programRequirements.forEach(({ prog, req }) => {
      const row = document.createElement('div');
      row.className = 'requirement-row';
      row.innerHTML = `<span><strong>Program:</strong> ${escapeHtml(prog.code)} — ${escapeHtml(prog.name)}</span><span>Course: ${escapeHtml(req.course_name || req.course_id)}</span>`;
      const editBtn = document.createElement('button');
      editBtn.className = 'ghost-btn small';
      editBtn.textContent = 'Edit';
      editBtn.onclick = () => openEditRequirementModal('program', prog.id, req.course_id, null);
      const delBtn = document.createElement('button');
      delBtn.className = 'danger-btn small';
      delBtn.textContent = 'Delete';
      delBtn.onclick = () => deleteRequirement('program', prog.id, req.course_id);
      row.appendChild(editBtn);
      row.appendChild(delBtn);
      root.appendChild(row);
    });
  }

  if (!groupOnlyRequirements.length && !groupTagRequirements.length && !programRequirements.length) {
    const emptyRow = document.createElement('div');
    emptyRow.className = 'requirement-row';
    emptyRow.textContent = 'No requirements defined yet.';
    root.appendChild(emptyRow);
  }
}

function checkExportAllowed() {
  if (!els.exportBtn) return;
  const unmet = getUnmetRequirements();
  els.exportBtn.disabled = unmet.length > 0;
  els.exportBtn.title = unmet.length ? `Cannot export: ${unmet.length} unmet requirement${unmet.length === 1 ? '' : 's'}.` : 'Export Excel';
}

function getUnmetRequirements() {
  const groups = state.data.groups || [];
  const cells = state.data.cells || {};
  const unmet = [];

  groups.forEach(group => {
    const groupLabel = `${group.code} — ${group.name}`;
    (group.requirements || []).forEach(req => {
      const sessionsRequired = req.sessions_required || 1;
      let deployedCount = 0;
      Object.values(cells).forEach(cellGroups => {
        const items = cellGroups[String(group.id)] || [];
        items.forEach(item => {
          if (item.course_id === req.course_id || item.course_name === req.course_name) {
            deployedCount += 1;
          }
        });
      });
      if (deployedCount < sessionsRequired) {
        const courseLabel = req.course_name || req.course_id;
        unmet.push(`Group ${groupLabel} needs ${sessionsRequired} ${courseLabel}, deployed ${deployedCount}`);
      }
    });
  });

  return unmet;
}

const state = {
  data: null,
  timetableId: null,
  selected: [],
  editingGroupId: null,
  openMenuGroupId: null,
  selectedProgramGroupId: null,
  editingEntity: { type: null, id: null },
};

const els = {};
const CRUD = {
  cycle: '/api/cycles',
  timetable: '/api/timetables',
  group_tag: '/api/group-tags',
  course_tag: '/api/course-tags',
  program: '/api/study-programs',
  room: '/api/rooms',
  teacher: '/api/teachers',
  course: '/api/courses',
};

window.addEventListener('DOMContentLoaded', () => {
  cacheEls();
  bindGlobalActions();
  bindExportWarning();
  refreshData();
});

function bindExportWarning() {
  if (!els.exportBtn) return;
  els.exportBtn.addEventListener('click', async function (e) {
    // Only intercept if href is set
    if (!els.exportBtn.href || els.exportBtn.href.endsWith('#')) return;
    // Check requirements before export
    const unmet = getUnmetRequirements();
    if (unmet.length) {
      e.preventDefault();
      alert('Cannot export:\n' + unmet.slice(0, 5).join('\n'));
      return;
    }
    e.preventDefault();
    await downloadExcel(els.exportBtn.href, 'Exporting...');
  });

  // Helper to check unmet requirements
  function hasUnmetRequirements() {
    const groups = state.data.groups || [];
    const cells = state.data.cells || {};
    for (const group of groups) {
      for (const req of (group.requirements || [])) {
        const sessionsRequired = req.sessions_required || 1;
        let deployedCount = 0;
        Object.values(cells).forEach(cellGroups => {
          const items = cellGroups[String(group.id)] || [];
          items.forEach(item => {
            if (item.course_name === req.course_name || item.course_id === req.course_id) {
              deployedCount += 1;
            }
          });
        });
        if (deployedCount < sessionsRequired) return true;
      }
    }
    return false;
  }
}

function cacheEls() {
  [
    'timetableBoard',
    'selectionText',
    'openAddClassBtn',
    'clearSelectionBtn',
    'refreshBtn',
    'teacherLoadList',
    'groupModal',
    'groupForm',
    'groupModalTitle',
    'groupTagSelect',
    'groupProgramOptions',
    'requirementRows',
    'selectAllGroupsBtn',
    'selectAllProgramsBtn',
    'addRequirementRowBtn',
    'deleteGroupBtn',
    'saveGroupBtn',
    'classModal',
    'classModalTitle',
    'classForm',
    'classSubmitBtn',
    'classTargetInfo',
    'courseSelect',
    'teacherSelect',
    'roomSelect',
    'programSelectionBox',
    'classProgramOptions',
    'groupSelectionBox',
    'classGroupOptions',
    'selectAllClassProgramsBtn',
    'clearClassProgramsBtn',
    'selectAllClassGroupsBtn',
    'clearClassGroupsBtn',
    'classErrors',
    'cycleSelect',
    'timetableSelect',
    'editCycleBtn',
    'deleteCycleBtn',
    'editTimetableBtn',
    'deleteTimetableBtn',
    'deployTimetableBtn',
    'exportBtn',
    'exportProgramBtn',
    'exportProgramModal',
    'exportProgramForm',
    'exportProgramOptions',
    'groupTagList',
    'courseTagList',
    'programList',
    'roomList',
    'teacherList',
    'courseList',
    'groupProgramPanel',
    'groupProgramPanelTitle',
    'groupProgramCheckboxes',
    'saveGroupProgramsBtn',
    'clearGroupProgramSelectionBtn',
    'groupProgramPanelMessage',
    'entityModal',
    'entityForm',
    'entityModalTitle',
    'entityDeleteBtn',
    'entityErrors',
    'entityCycleSelect',
    'entityCourseTagSelect',
    'entityTeacherTags',
    'entityCoursePrograms',
    'entityRequirementRows',
    'addEntityRequirementBtn',
    'addGroupTagRequirementPanelBtn',
    'addStudyProgramRequirementPanelBtn',
    'addGroupOnlyRequirementPanelBtn',
    'addGroupTagRequirementBtn',
    'addStudyProgramRequirementBtn',
  ].forEach(id => {
    els[id] = document.getElementById(id);
  });
  els.requirementRowTemplate = document.getElementById('requirementRowTemplate');
  els.addRequirementModal = document.getElementById('addRequirementModal');
  els.addRequirementForm = document.getElementById('addRequirementForm');
  els.addRequirementModalTitle = document.getElementById('addRequirementModalTitle');
  els.requirementTagOrProgramLabel = document.getElementById('requirementTagOrProgramLabel');
  els.requirementTagOrProgramText = document.getElementById('requirementTagOrProgramText');
  els.requirementTagOrProgramSelect = document.getElementById('requirementTagOrProgramSelect');
  els.requirementCourseSelect = document.getElementById('requirementCourseSelect');
  els.requirementSessionsInput = document.getElementById('requirementSessionsInput');
  els.requirementSessionsRow = document.getElementById('requirementSessionsRow');
  els.classForm = document.getElementById('classForm');
  els.classModalTitle = document.getElementById('classModalTitle');
  els.classSubmitBtn = document.getElementById('classSubmitBtn');
  els.classUpdateWarning = document.getElementById('classUpdateWarning');
  els.programSelectionBox = document.getElementById('programSelectionBox');
  els.classProgramOptions = document.getElementById('classProgramOptions');
  els.programClassHint = document.getElementById('programClassHint');
  els.groupOnlyRequirementModal = document.getElementById('groupOnlyRequirementModal');
  els.groupOnlyRequirementForm = document.getElementById('groupOnlyRequirementForm');
  els.groupOnlyRequirementGroupSelect = document.getElementById('groupOnlyRequirementGroupSelect');
  els.groupOnlyRequirementCourseSelect = document.getElementById('groupOnlyRequirementCourseSelect');
  els.groupOnlyRequirementSessionsInput = document.getElementById('groupOnlyRequirementSessionsInput');
  els.requirementSessionsInput = document.getElementById('requirementSessionsInput');
  els.requirementSessionsRow = document.getElementById('requirementSessionsRow');
}

function bindGlobalActions() {
  if (els.addGroupTagRequirementPanelBtn) {
    els.addGroupTagRequirementPanelBtn.addEventListener('click', () => {
      console.log('Clicked: addGroupTagRequirementPanelBtn');
      openAddRequirementModal('group_tag');
    });
  } else {
    console.warn('Missing element: addGroupTagRequirementPanelBtn');
  }
  if (els.addStudyProgramRequirementPanelBtn) {
    els.addStudyProgramRequirementPanelBtn.addEventListener('click', () => {
      console.log('Clicked: addStudyProgramRequirementPanelBtn');
      openAddRequirementModal('program');
    });
  } else {
    console.warn('Missing element: addStudyProgramRequirementPanelBtn');
  }
  if (els.addGroupOnlyRequirementPanelBtn) {
    els.addGroupOnlyRequirementPanelBtn.addEventListener('click', () => {
      openGroupOnlyRequirementModal();
    });
  } else {
    console.warn('Missing element: addGroupOnlyRequirementPanelBtn');
  }
  if (els.addGroupTagRequirementBtn) {
    els.addGroupTagRequirementBtn.addEventListener('click', () => openAddRequirementModal('group_tag'));
  }
  if (els.addStudyProgramRequirementBtn) {
    els.addStudyProgramRequirementBtn.addEventListener('click', () => openAddRequirementModal('program'));
  }
  if (els.addRequirementForm) {
    els.addRequirementForm.addEventListener('submit', submitAddRequirementForm);
  }
  if (els.groupOnlyRequirementForm) {
    els.groupOnlyRequirementForm.addEventListener('submit', submitGroupOnlyRequirementForm);
  }
  if (els.selectAllGroupsBtn) {
    els.selectAllGroupsBtn.addEventListener('click', () => {
      document.querySelectorAll('#requirementRows .group-checkbox input[type="checkbox"]').forEach(cb => {
        cb.checked = true;
        cb.dispatchEvent(new Event('change'));
      });
    });
  } else {
    console.warn('Missing element: selectAllGroupsBtn');
  }
  if (els.selectAllProgramsBtn) {
    els.selectAllProgramsBtn.addEventListener('click', () => {
      document.querySelectorAll('#requirementRows .program-checkbox input[type="checkbox"]').forEach(cb => {
        cb.checked = true;
        cb.dispatchEvent(new Event('change'));
      });
    });
  } else {
    console.warn('Missing element: selectAllProgramsBtn');
  }
  if (els.clearSelectionBtn) {
    els.clearSelectionBtn.addEventListener('click', clearSelection);
  } else {
    console.warn('Missing element: clearSelectionBtn');
  }
  if (els.openAddClassBtn) {
    els.openAddClassBtn.addEventListener('click', openClassModal);
  } else {
    console.warn('Missing element: openAddClassBtn');
  }
  if (els.refreshBtn) {
    els.refreshBtn.addEventListener('click', refreshData);
  } else {
    console.warn('Missing element: refreshBtn');
  }
  if (els.exportProgramBtn) {
    els.exportProgramBtn.addEventListener('click', openExportProgramModal);
  }
  if (els.exportProgramForm) {
    els.exportProgramForm.addEventListener('submit', submitExportProgramForm);
  }
  if (els.addRequirementRowBtn) {
    els.addRequirementRowBtn.addEventListener('click', () => addRequirementRow());
  } else {
    console.warn('Missing element: addRequirementRowBtn');
  }
  if (els.saveGroupProgramsBtn) {
    els.saveGroupProgramsBtn.addEventListener('click', saveGroupPrograms);
  }
  if (els.clearGroupProgramSelectionBtn) {
    els.clearGroupProgramSelectionBtn.addEventListener('click', () => {
      state.selectedProgramGroupId = null;
      renderGroupProgramPanel();
    });
  }
  if (els.deleteGroupBtn) {
    els.deleteGroupBtn.addEventListener('click', deleteCurrentGroup);
  } else {
    console.warn('Missing element: deleteGroupBtn');
  }
  if (els.addEntityRequirementBtn) {
    els.addEntityRequirementBtn.addEventListener('click', () => addEntityRequirementRow());
  } else {
    console.warn('Missing element: addEntityRequirementBtn');
  }

  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
  });

  document.querySelectorAll('[data-open-entity]').forEach(btn => {
    btn.addEventListener('click', () => openEntityModal(btn.dataset.openEntity));
  });

  document.querySelectorAll('[data-jump]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = document.querySelector(btn.dataset.jump);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  const manageMenuBtn = document.getElementById('manageMenuBtn');
  const manageMenuDropdown = document.getElementById('manageMenuDropdown');
  if (manageMenuBtn && manageMenuDropdown) {
    manageMenuBtn.addEventListener('click', event => {
      event.stopPropagation();
      manageMenuDropdown.classList.toggle('hidden');
    });
    manageMenuDropdown.addEventListener('click', event => event.stopPropagation());
    document.addEventListener('click', () => {
      manageMenuDropdown.classList.add('hidden');
    });
  }

  document.addEventListener('click', event => {
    if (!event.target.closest('.group-menu-wrap')) {
      state.openMenuGroupId = null;
      if (state.data) renderBoard();
    }
  });

  if (els.groupForm) {
    els.groupForm.addEventListener('submit', submitGroupForm);
  } else {
    console.warn('Missing element: groupForm');
  }
  if (els.classForm) {
    els.classForm.addEventListener('submit', submitClassForm);
    els.classForm.querySelectorAll('input[name="mode"]').forEach(radio => {
      radio.addEventListener('change', syncClassFormVisibility);
    });
  } else {
    console.warn('Missing element: classForm');
  }
  if (els.selectAllClassProgramsBtn) {
    els.selectAllClassProgramsBtn.addEventListener('click', () => {
      els.classProgramOptions?.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
      syncClassFormVisibility();
    });
  }
  if (els.clearClassProgramsBtn) {
    els.clearClassProgramsBtn.addEventListener('click', () => {
      els.classProgramOptions?.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
      syncClassFormVisibility();
    });
  }
  if (els.selectAllClassGroupsBtn) {
    els.selectAllClassGroupsBtn.addEventListener('click', () => {
      els.classGroupOptions?.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        if (!cb.disabled) cb.checked = true;
      });
    });
  }
  if (els.clearClassGroupsBtn) {
    els.clearClassGroupsBtn.addEventListener('click', () => {
      els.classGroupOptions?.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
    });
  }
  if (els.entityForm) {
    els.entityForm.addEventListener('submit', submitEntityForm);
  } else {
    console.warn('Missing element: entityForm');
  }
  if (els.entityDeleteBtn) {
    els.entityDeleteBtn.addEventListener('click', deleteCurrentEntity);
  } else {
    console.warn('Missing element: entityDeleteBtn');
  }
  if (els.cycleSelect) {
    els.cycleSelect.addEventListener('change', handleCycleChange);
  } else {
    console.warn('Missing element: cycleSelect');
  }
  if (els.timetableSelect) {
    els.timetableSelect.addEventListener('change', handleTimetableChange);
  } else {
    console.warn('Missing element: timetableSelect');
  }
  if (els.editCycleBtn) {
    els.editCycleBtn.addEventListener('click', () => {
      const id = toNullableNumber(els.cycleSelect.value);
      if (id) openEntityModal('cycle', id);
    });
  } else {
    console.warn('Missing element: editCycleBtn');
  }
  if (els.deleteCycleBtn) {
    els.deleteCycleBtn.addEventListener('click', () => {
      const id = toNullableNumber(els.cycleSelect.value);
      if (id) deleteEntity('cycle', id, 'Delete this cycle?');
    });
  } else {
    console.warn('Missing element: deleteCycleBtn');
  }
  if (els.editTimetableBtn) {
    els.editTimetableBtn.addEventListener('click', () => {
      const id = toNullableNumber(els.timetableSelect.value);
      if (id) openEntityModal('timetable', id);
    });
  } else {
    console.warn('Missing element: editTimetableBtn');
  }
  if (els.deleteTimetableBtn) {
    els.deleteTimetableBtn.addEventListener('click', () => {
      const id = toNullableNumber(els.timetableSelect.value);
      if (id) deleteEntity('timetable', id, 'Delete this timetable and all groups/classes inside it?');
    });
  } else {
    console.warn('Missing element: deleteTimetableBtn');
  }
  if (els.deployTimetableBtn) {
    els.deployTimetableBtn.addEventListener('click', deployCurrentTimetable);
  } else {
    console.warn('Missing element: deployTimetableBtn');
  }
}
    
function showError(msg) {
  let el = document.getElementById('js-fallback-message');
  if (!el) {
    el = document.createElement('div');
    el.id = 'js-fallback-message';
    el.style.color = 'red';
    el.style.fontWeight = 'bold';
    document.body.prepend(el);
  }
  el.textContent = msg;
  el.style.display = 'block';
}

function renderContextSelectors() {
  // Debug log
  console.log('renderContextSelectors: cycles', state.data.cycles);
  fillSelect(
    els.cycleSelect,
    (state.data.cycles || []).map(item => ({ value: item.id, label: `${item.name} (${item.year_starting})` })),
    true
  );
  let selectedCycleId = state.data.selected_cycle_id || null;
  if (!selectedCycleId && state.data.cycles?.length) {
    selectedCycleId = state.data.cycles[0].id;
  }
  if (selectedCycleId) {
    els.cycleSelect.value = String(selectedCycleId);
  }
  // Debug log
  console.log('renderContextSelectors: timetables', state.data.timetables);
  const timetableOptions = (state.data.timetables || [])
    .filter(item => !selectedCycleId || item.cycle_id === Number(selectedCycleId))
    .map(item => ({
      value: item.id,
      label: `Timetable #${item.id}${item.in_action ? ' • current' : ''}`,
    }));
  fillSelect(els.timetableSelect, timetableOptions, true);
  if (state.timetableId && timetableOptions.some(item => Number(item.value) === Number(state.timetableId))) {
    els.timetableSelect.value = String(state.timetableId);
  } else if (timetableOptions.length) {
    els.timetableSelect.value = String(timetableOptions[0].value);
    state.timetableId = Number(timetableOptions[0].value);
  } else {
    state.timetableId = null;
  }
  // Debug log
  console.log('renderContextSelectors: cycleSelect.innerHTML', els.cycleSelect.innerHTML);
  console.log('renderContextSelectors: timetableSelect.innerHTML', els.timetableSelect.innerHTML);
  els.exportBtn.href = state.timetableId ? `/export.xlsx?timetable_id=${state.timetableId}` : '/export.xlsx';
  if (els.exportProgramOptions) {
    els.exportProgramOptions.innerHTML = '';
    renderProgramCheckboxes(els.exportProgramOptions, state.data.programs || [], 'exportPrograms', 'code');
  }
  if (els.exportProgramBtn) {
    els.exportProgramBtn.disabled = !state.timetableId || !(state.data.programs || []).length;
  }
  els.deployTimetableBtn.disabled = !state.timetableId;
  els.editTimetableBtn.disabled = !state.timetableId;
  els.deleteTimetableBtn.disabled = !state.timetableId;
  els.openAddClassBtn.disabled = !state.selected.length;
}

async function handleCycleChange() {
  const cycleId = toNullableNumber(els.cycleSelect.value);
  const timetableOptions = (state.data.timetables || []).filter(item => !cycleId || item.cycle_id === cycleId);
  state.timetableId = timetableOptions.length ? timetableOptions[0].id : null;
  await refreshData(state.timetableId);
}

async function handleTimetableChange() {
  state.timetableId = toNullableNumber(els.timetableSelect.value);
  await refreshData(state.timetableId);
}

async function deployCurrentTimetable() {
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  const res = await fetch(`/api/timetables/${state.timetableId}/deploy`, { method: 'POST' });
  const data = await safeJson(res);
  if (!res.ok) {
    alert(formatError(data));
    return;
  }
  state.data = data;
  state.timetableId = state.data.selected_timetable_id || state.timetableId;
  renderContextSelectors();
  renderEntityLists();
  renderBoard();
  renderTeacherLoad();
}

function renderEntityLists() {
  renderEntityList('groupTagList', state.data.group_tags || [], 'group_tag', item => `${item.code} — ${item.name}`);
  renderEntityList('courseTagList', state.data.course_tags || [], 'course_tag', item => item.name);
  renderEntityList('programList', state.data.programs || [], 'program', item => `${item.code} — ${item.name}`);
  renderEntityList('roomList', state.data.rooms || [], 'room', item => `${item.code} — ${item.name}`, item => `Cap ${item.capacity}`);
  renderEntityList('teacherList', state.data.teachers || [], 'teacher', item => item.name, item => `Tags: ${item.course_tag_ids.length}`);
  renderEntityList('courseList', state.data.courses || [], 'course', item => `${item.code} — ${item.name}`, item => item.require_all ? 'Require all' : (item.elective ? 'Elective' : 'Program class'));
}

function renderEntityList(containerId, items, type, labelFn, metaFn = null) {
  const root = els[containerId];
  root.innerHTML = '';
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'entity-row';
    row.innerHTML = `
      <div class="entity-text">
        <div>${escapeHtml(labelFn(item))}</div>
        ${metaFn ? `<small>${escapeHtml(metaFn(item))}</small>` : ''}
      </div>
      <div class="entity-actions">
        <button class="ghost-btn small" data-edit-entity="${type}:${item.id}">Edit</button>
        <button class="danger-btn small" data-delete-entity="${type}:${item.id}">Delete</button>
      </div>`;
    root.appendChild(row);
  });

  root.querySelectorAll('[data-edit-entity]').forEach(btn => {
    const [type, id] = btn.dataset.editEntity.split(':');
    btn.addEventListener('click', () => openEntityModal(type, Number(id)));
  });
  root.querySelectorAll('[data-delete-entity]').forEach(btn => {
    const [type, id] = btn.dataset.deleteEntity.split(':');
    btn.addEventListener('click', () => deleteEntity(type, Number(id), `Delete this ${type.replace('_', ' ')}?`));
  });
}

function populateStaticInputs() {
  fillSelect(
    els.groupTagSelect,
    (state.data.group_tags || []).map(item => ({ value: item.id, label: `${item.code} — ${item.name}` })),
    true
  );

  fillSelect(
    els.entityCycleSelect,
    (state.data.cycles || []).map(item => ({ value: item.id, label: `${item.name} (${item.year_starting})` })),
    true
  );

  fillSelect(
    els.entityCourseTagSelect,
    (state.data.course_tags || []).map(item => ({ value: item.id, label: item.name })),
    true
  );

  renderProgramCheckboxes(els.groupProgramOptions, state.data.programs || [], 'groupPrograms');
  renderProgramCheckboxes(els.entityCoursePrograms, state.data.programs || [], 'entityPrograms');
  renderProgramCheckboxes(els.entityTeacherTags, state.data.course_tags || [], 'entityTeacherTags', 'name');
  fillSelect(
    els.roomSelect,
    [{ value: '', label: 'No room' }, ...(state.data.rooms || []).map(r => ({ value: r.id, label: `${r.code} (${r.capacity})` }))],
    false
  );
  syncClassFormVisibility();
}

function renderTeacherLoad() {
  els.teacherLoadList.innerHTML = '';
  (state.data.teacher_load || []).forEach(item => {
    const div = document.createElement('div');
    div.className = 'teacher-load-row';
    div.innerHTML = `<span>${escapeHtml(item.teacher)}</span><strong>${item.timeslot_count}</strong>`;
    els.teacherLoadList.appendChild(div);
  });
}

function itemRowKey(item) {
  if (item.kind === 'required') {
    return item.kind;
  }
  return [
    item.kind,
    item.course_name,
    item.teacher_name,
    item.room_name,
  ].join('||');
}

function getSelectValues(select) {
  return Array.from(select.selectedOptions).map(option => Number(option.value)).filter(val => !!val);
}

function setSelectValues(select, values) {
  const selectedIds = new Set(values.map(Number));
  Array.from(select.options).forEach(option => {
    option.selected = selectedIds.has(Number(option.value));
  });
}

function renderBoard() {
  const groups = state.data.groups || [];
  const timeslots = [...(state.data.timeslots || [])].sort((a, b) => a.sort_order - b.sort_order);
  const cells = state.data.cells || {};

  els.timetableBoard.innerHTML = '';

  const thead = document.createElement('thead');
  const hrow = document.createElement('tr');
  hrow.innerHTML = `<th class="time-header">Day</th><th class="time-header">Time</th>`;
  groups.forEach((group, idx) => {
    const th = document.createElement('th');
    th.className = 'group-header';
    th.setAttribute('draggable', 'true');
    th.dataset.groupId = group.id;
    th.dataset.idx = idx;
    const isOpen = state.openMenuGroupId === group.id;
    th.innerHTML = `
      <div class="group-header-top">
        <div class="group-title-wrap">
          <div class="group-code">${escapeHtml(group.code)}</div>
          <small>${escapeHtml(group.programs.map(p => p.code).join('/'))}</small>
        </div>
        <div class="group-menu-wrap">
          <button class="dots-btn" data-group-menu="${group.id}" title="Group options">⋯</button>
          <div class="group-menu ${isOpen ? '' : 'hidden'}">
            <button type="button" data-edit-group="${group.id}">Adjust group</button>
            <button type="button" data-open-programs="${group.id}">Edit programs</button>
            <button type="button" data-delete-group="${group.id}" class="danger-text">Delete group</button>
          </div>
        </div>
      </div>`;
    // Drag events
    th.addEventListener('dragstart', (e) => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', idx);
      th.classList.add('dragging');
    });
    th.addEventListener('dragend', () => {
      th.classList.remove('dragging');
    });
    th.addEventListener('dragover', (e) => {
      e.preventDefault();
      th.classList.add('drag-over');
    });
    th.addEventListener('dragleave', () => {
      th.classList.remove('drag-over');
    });
    th.addEventListener('drop', (e) => {
      e.preventDefault();
      th.classList.remove('drag-over');
      const fromIdx = Number(e.dataTransfer.getData('text/plain'));
      const toIdx = idx;
      if (fromIdx !== toIdx) {
        reorderGroups(fromIdx, toIdx);
      }
    });
    hrow.appendChild(th);
  });
  const addTh = document.createElement('th');
  addTh.className = 'add-group-col';
  addTh.innerHTML = `<button class="plus-btn" id="openGroupModalBtn" title="Add group">＋</button>`;
  hrow.appendChild(addTh);
  thead.appendChild(hrow);
  els.timetableBoard.appendChild(thead);

  document.getElementById('openGroupModalBtn').addEventListener('click', () => openGroupModal());
  // Reorder groups in state.data.groups and re-render
  async function reorderGroups(fromIdx, toIdx) {
    if (!Array.isArray(state.data.groups)) return;
    const arr = state.data.groups;
    const [moved] = arr.splice(fromIdx, 1);
    arr.splice(toIdx, 0, moved);
    const payload = { group_ids: arr.map(group => group.id) };
    const res = await fetch('/api/groups/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await safeJson(res);
    if (!res.ok) {
      alert(formatError(data));
      return;
    }
    state.data = data;
    renderBoard();
  }
  els.timetableBoard.querySelectorAll('[data-group-menu]').forEach(btn => {
    btn.addEventListener('click', event => {
      event.stopPropagation();
      const groupId = Number(btn.dataset.groupMenu);
      state.openMenuGroupId = state.openMenuGroupId === groupId ? null : groupId;
      renderBoard();
    });
  });
  els.timetableBoard.querySelectorAll('[data-edit-group]').forEach(btn => {
    btn.addEventListener('click', event => {
      event.stopPropagation();
      openGroupModal(Number(btn.dataset.editGroup));
    });
  });
  els.timetableBoard.querySelectorAll('[data-open-programs]').forEach(btn => {
    btn.addEventListener('click', event => {
      event.stopPropagation();
      openGroupModal(Number(btn.dataset.openPrograms));
    });
  });
  els.timetableBoard.querySelectorAll('[data-delete-group]').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.stopPropagation();
      await deleteGroupById(Number(btn.dataset.deleteGroup));
    });
  });

  const slotRowMap = {};
  timeslots.forEach(slot => {
    const rowKeys = [];
    const groupItemsByKey = {};
    groups.forEach(group => {
      const items = (cells[String(slot.id)] || {})[String(group.id)] || [];
      const map = {};
      items.forEach(item => {
        const key = itemRowKey(item);
        if (!rowKeys.includes(key)) {
          rowKeys.push(key);
        }
        map[key] = item;
      });
      groupItemsByKey[String(group.id)] = map;
    });
    rowKeys.sort((a, b) => {
      const rank = { required: 0, program: 1, elective: 2 };
      const [akey] = a.split('||');
      const [bkey] = b.split('||');
      const delta = (rank[akey] ?? 3) - (rank[bkey] ?? 3);
      return delta !== 0 ? delta : a.localeCompare(b);
    });
    slotRowMap[String(slot.id)] = { keys: rowKeys, groupItemsByKey };
  });

  const tbody = document.createElement('tbody');
  const days = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY'];
  days.forEach(day => {
    const daySlots = timeslots.filter(slot => slot.weekday === day);
    daySlots.forEach((slot, index) => {
      const tr = document.createElement('tr');
      if (index === 0) {
        const dayCell = document.createElement('td');
        dayCell.className = 'day-cell';
        dayCell.rowSpan = daySlots.length + 1;
        dayCell.textContent = day.replace('DAY', '');
        tr.appendChild(dayCell);
      }

      const timeTd = document.createElement('td');
      timeTd.className = 'slot-label';
      timeTd.textContent = slot.label;
      tr.appendChild(timeTd);

      const rowKeys = slotRowMap[String(slot.id)]?.keys || [];
      const rows = Math.max(6, rowKeys.length);

      groups.forEach(group => {
        const td = document.createElement('td');
        td.className = 'timetable-cell';

        const items = (cells[String(slot.id)] || {})[String(group.id)] || [];
        if (items.some(item => item.kind === 'required')) td.classList.add('expanded');
        if (isSelected(group.id, slot.id)) td.classList.add('selected');

        td.addEventListener('click', event => handleCellClick(event, group.id, group.code, slot.id, slot));

        const stack = document.createElement('div');
        stack.className = 'strip-stack';
        stack.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
        stack.style.height = `${rows * 140}px`;
        stack.style.minHeight = `${rows * 140}px`;

        const itemsByKey = slotRowMap[String(slot.id)]?.groupItemsByKey[String(group.id)] || {};
        for (let i = 0; i < rows; i += 1) {
          const strip = document.createElement('div');
          strip.className = 'strip empty';
          const item = itemsByKey[rowKeys[i]];
          if (item) {
            strip.className = `strip filled ${item.color_key} ${item.kind}`;
            strip.innerHTML = renderStrip(item);
          }
          stack.appendChild(strip);
        }
        td.appendChild(stack);
        tr.appendChild(td);
        // Add event delegation for class edit/delete
        stack.addEventListener('click', async (e) => {
          if (e.target.matches('[data-delete-class]')) {
            e.stopPropagation();
            const classId = e.target.getAttribute('data-delete-class');
            const mergedCount = Number(e.target.dataset.mergedCount || 1);
            const message = mergedCount > 1
              ? `This merged program block contains ${mergedCount} program classes. Deleting one will update the merged display. Continue?`
              : 'Delete this class?';
            if (confirm(message)) {
              await fetch(`/api/classes/${classId}`, { method: 'DELETE' });
              await refreshData();
            }
          } else if (e.target.matches('[data-edit-class]')) {
            e.stopPropagation();
            const classId = e.target.getAttribute('data-edit-class');
            openClassModal(classId);
          }
        });
      });

      const filler = document.createElement('td');
      filler.className = 'add-group-col cell-filler';
      tr.appendChild(filler);
      tbody.appendChild(tr);

      if (index === 0) {
        const lunch = document.createElement('tr');
        lunch.className = 'lunch-row';
        lunch.innerHTML = `<td class="slot-label lunch">Lunch break</td><td colspan="${groups.length + 1}"></td>`;
        tbody.appendChild(lunch);
      }
    });
  });

  els.timetableBoard.appendChild(tbody);
  renderGroupProgramPanel();
}

function openGroupProgramPanel(groupId) {
  state.selectedProgramGroupId = groupId;
  renderGroupProgramPanel();
  if (els.groupProgramPanel) {
    els.groupProgramPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderGroupProgramPanel() {
  if (!els.groupProgramPanel) return;
  const groupId = state.selectedProgramGroupId;
  const group = (state.data?.groups || []).find(g => g.id === groupId);
  if (!group) {
    els.groupProgramPanelTitle.textContent = 'Select a group from the board to edit its programs.';
    els.groupProgramCheckboxes.innerHTML = '';
    els.saveGroupProgramsBtn?.classList.add('hidden');
    els.clearGroupProgramSelectionBtn?.classList.add('hidden');
    els.groupProgramPanelMessage.textContent = '';
    return;
  }
  els.groupProgramPanelTitle.textContent = `Group ${group.code} programs`;
  renderProgramCheckboxes(els.groupProgramCheckboxes, state.data.programs || [], 'groupProgramPanelPrograms');
  const currentProgramIds = new Set((group.programs || []).map(p => p.id));
  const checkboxes = els.groupProgramCheckboxes.querySelectorAll('input[type="checkbox"]');
  checkboxes.forEach(input => {
    input.checked = currentProgramIds.has(Number(input.value));
  });
  if (checkboxes.length === 0) {
    els.groupProgramPanelMessage.textContent = 'No study programs are defined yet. Add programs under Study programs first.';
    els.saveGroupProgramsBtn?.classList.add('hidden');
    els.clearGroupProgramSelectionBtn?.classList.add('hidden');
  } else {
    els.groupProgramPanelMessage.textContent = 'Select programs for this group and click Save.';
    els.saveGroupProgramsBtn?.classList.remove('hidden');
    els.clearGroupProgramSelectionBtn?.classList.remove('hidden');
  }
}

async function saveGroupPrograms() {
  const groupId = state.selectedProgramGroupId;
  if (!groupId) return;
  const group = (state.data?.groups || []).find(g => g.id === groupId);
  if (!group) return;
  const payload = {
    timetable_id: group.timetable_id,
    code: group.code,
    name: group.name,
    group_tag_id: group.group_tag?.id ?? null,
    capacity: group.capacity,
    study_program_ids: collectCheckedValues(els.groupProgramCheckboxes),
    requirements: group.requirements || [],
  };
  const res = await fetch(`/api/groups/${groupId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await safeJson(res);
  if (!res.ok) {
    els.groupProgramPanelMessage.textContent = formatError(data);
    return;
  }
  state.data = data;
  renderContextSelectors();
  renderEntityLists();
  renderBoard();
  renderTeacherLoad();
  populateStaticInputs();
  renderGroupProgramPanel();
  els.groupProgramPanelMessage.textContent = 'Programs saved.';
}

function renderStrip(item) {
  const courseHtml = `<div class="strip-title">${escapeHtml(item.course_name)}</div>`;
  const programHtml = item.program_codes.length ? `<div class="strip-programs">${escapeHtml(item.program_codes.join(', '))}</div>` : '';
  const groupHtml = item.group_codes?.length ? `<div class="strip-groups">${escapeHtml(item.group_codes.join(', '))}</div>` : '';
  const teacherHtml = item.teacher_name ? `<span class="strip-meta">${escapeHtml(item.teacher_name)}</span>` : '';
  const roomHtml = item.room_name ? `<span class="strip-meta">${escapeHtml(item.room_name)}</span>` : '';
  const mergedNote = item.kind === 'program' && item.class_ids?.length > 1
    ? `<div class="strip-note">Merged program classes — edit/delete may affect the merged block.</div>`
    : '';
  const buttonHtml = item.class_ids?.length
    ? `<div class="strip-footer"><button type="button" class="danger-btn small inline-delete" data-delete-class="${item.class_ids[0]}" data-merged-count="${item.class_ids.length}">${item.class_ids.length > 1 ? 'Delete bundle' : 'Delete'}</button><button type="button" class="ghost-btn small inline-edit" data-edit-class="${item.class_ids[0]}" data-merged-count="${item.class_ids.length}">${item.class_ids.length > 1 ? 'Edit bundle' : 'Edit'}</button></div>`
    : '';

  return `
    <div class="strip-top">
      <div class="strip-main">${courseHtml}${programHtml}${groupHtml}${mergedNote}</div>
      <div class="strip-side">${teacherHtml}${roomHtml}</div>
    </div>
    ${buttonHtml}
  `;
}

function handleCellClick(event, groupId, groupCode, timeslotId, slot) {
  const sameRow = state.selected.length === 0 || state.selected[0].timeslotId === timeslotId;
  const allowMulti = event.ctrlKey || event.metaKey;

  if (!allowMulti || !sameRow) {
    state.selected = [];
  }

  const existingIndex = state.selected.findIndex(item => item.groupId === groupId && item.timeslotId === timeslotId);
  if (existingIndex >= 0) {
    state.selected.splice(existingIndex, 1);
  } else {
    state.selected.push({ groupId, groupCode, timeslotId, slotLabel: `${slot.weekday} ${slot.label}` });
  }

  updateSelectionUI();
  renderBoard();

  if (!allowMulti && state.selected.length === 1) {
    openClassModal();
  }
}

function updateSelectionUI() {
  if (!state.selected.length) {
    els.selectionText.textContent = 'No cells selected.';
    els.openAddClassBtn.disabled = true;
    return;
  }
  const codes = state.selected.map(item => item.groupCode).join(', ');
  els.selectionText.textContent = `${state.selected[0].slotLabel} → ${codes}`;
  els.openAddClassBtn.disabled = false;
}

function clearSelection(shouldRender = true) {
  state.selected = [];
  updateSelectionUI();
  if (state.data && shouldRender) renderBoard();
}

function isSelected(groupId, timeslotId) {
  return state.selected.some(item => item.groupId === groupId && item.timeslotId === timeslotId);
}

function openEntityModal(type, id = null) {
  state.editingEntity = { type, id };
  els.entityForm.reset();
  els.entityErrors.innerHTML = '';
  els.entityDeleteBtn.classList.toggle('hidden', !id);

  toggleEntityFields(type);

  const titleMap = {
    cycle: 'Cycle',
    timetable: 'Timetable',
    group_tag: 'Group tag',
    course_tag: 'Course tag',
    program: 'Study program',
    room: 'Room',
    teacher: 'Teacher',
    course: 'Course',
  };
  els.entityModalTitle.textContent = `${id ? 'Edit' : 'Add'} ${titleMap[type]}`;

  els.entityForm.elements.entity_type.value = type;
  els.entityForm.elements.entity_id.value = id || '';
  fillSelect(
    els.entityCycleSelect,
    (state.data.cycles || []).map(item => ({ value: item.id, label: `${item.name} (${item.year_starting})` })),
    true
  );
  fillSelect(
    els.entityCourseTagSelect,
    (state.data.course_tags || []).map(item => ({ value: item.id, label: item.name })),
    true
  );
  renderProgramCheckboxes(els.entityTeacherTags, state.data.course_tags || [], 'entityTeacherTags', 'name');
  renderProgramCheckboxes(els.entityCoursePrograms, state.data.programs || [], 'entityCoursePrograms');
  els.entityRequirementRows.innerHTML = '';

  if (id) {
    const item = getEntityById(type, id);
    if (!item) return;

    if (type === 'cycle') {
      els.entityForm.elements.name.value = item.name;
      els.entityForm.elements.year_starting.value = item.year_starting;
    } else if (type === 'timetable') {
      els.entityCycleSelect.value = String(item.cycle_id);
      els.entityForm.elements.in_action.checked = !!item.in_action;
    } else if (type === 'group_tag') {
      els.entityForm.elements.code.value = item.code;
      els.entityForm.elements.name.value = item.name;
      (item.requirements || []).forEach(req => addEntityRequirementRow(req.course_id, req.sessions_required));
    } else if (type === 'course_tag') {
      els.entityForm.elements.name.value = item.name;
    } else if (type === 'program') {
      els.entityForm.elements.code.value = item.code;
      els.entityForm.elements.name.value = item.name;
    } else if (type === 'room') {
      els.entityForm.elements.code.value = item.code;
      els.entityForm.elements.name.value = item.name;
      els.entityForm.elements.capacity.value = item.capacity;
    } else if (type === 'teacher') {
      els.entityForm.elements.name.value = item.name;
      precheckPrograms(els.entityTeacherTags, item.course_tag_ids);
    } else if (type === 'course') {
      els.entityForm.elements.code.value = item.code;
      els.entityForm.elements.name.value = item.name;
      els.entityCourseTagSelect.value = String(item.course_tag_id);
      els.entityForm.elements.require_all.checked = !!item.require_all;
      els.entityForm.elements.elective.checked = !!item.elective;
      precheckPrograms(els.entityCoursePrograms, item.study_program_ids);
    }
  } else {
    if (type === 'timetable') {
      const cycleId = toNullableNumber(els.cycleSelect.value);
      if (cycleId) els.entityCycleSelect.value = String(cycleId);
    }
    if (type === 'group_tag') {
      addEntityRequirementRow();
    }
  }

  openModal('entityModal');
}

function getEntityById(type, id) {
  const map = {
    cycle: 'cycles',
    timetable: 'timetables',
    group_tag: 'group_tags',
    course_tag: 'course_tags',
    program: 'programs',
    room: 'rooms',
    teacher: 'teachers',
    course: 'courses',
  };
  return (state.data[map[type]] || []).find(item => item.id === id);
}

function toggleEntityFields(type) {
  const show = (id, visible) => document.getElementById(id).classList.toggle('hidden', !visible);
  show('entityNameWrap', ['cycle', 'group_tag', 'course_tag', 'program', 'room', 'teacher', 'course'].includes(type));
  show('entityCodeWrap', ['group_tag', 'program', 'room', 'course'].includes(type));
  show('entityYearWrap', type === 'cycle');
  show('entityCapacityWrap', type === 'room');
  show('entityCycleWrap', type === 'timetable');
  show('entityCourseTagWrap', type === 'course');
  show('entityInActionWrap', type === 'timetable');
  show('entityTeacherTagsWrap', type === 'teacher');
  show('entityCourseProgramsWrap', false);
  show('entityCourseFlagsWrap', type === 'course');
  show('entityRequirementsWrap', false);
}

function addEntityRequirementRow(courseId = null, sessionsRequired = 1) {
  const clone = els.requirementRowTemplate.content.firstElementChild.cloneNode(true);
  const courseSelect = clone.querySelector('.requirement-course');
  const options = (state.data.courses || []).filter(c => !c.elective).map(c => ({ value: c.id, label: c.name }));
  fillSelect(courseSelect, options, true);
  if (courseId) courseSelect.value = String(courseId);
  clone.querySelector('.requirement-count').value = sessionsRequired;
  clone.querySelector('.remove-row-btn').addEventListener('click', () => clone.remove());
  els.entityRequirementRows.appendChild(clone);
}

async function submitEntityForm(event) {
  event.preventDefault();
  const type = els.entityForm.elements.entity_type.value;
  const id = toNullableNumber(els.entityForm.elements.entity_id.value);
  const url = id ? `${CRUD[type]}/${id}` : CRUD[type];
  const method = id ? 'PUT' : 'POST';
  const payload = buildEntityPayload(type);

  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await safeJson(res);
  if (!res.ok) {
    els.entityErrors.textContent = formatError(data);
    return;
  }
  state.data = data;
  state.timetableId = state.data.selected_timetable_id || state.timetableId;
  closeModal('entityModal');
  renderContextSelectors();
  renderEntityLists();
  renderBoard();
  renderTeacherLoad();
  populateStaticInputs();
}

function buildEntityPayload(type) {
  const f = els.entityForm.elements;
  if (type === 'cycle') {
    return {
      name: f.name.value,
      year_starting: Number(f.year_starting.value),
    };
  }
  if (type === 'timetable') {
    return {
      cycle_id: Number(els.entityCycleSelect.value),
      in_action: !!f.in_action.checked,
    };
  }
  if (type === 'group_tag') {
    return {
      code: f.code.value,
      name: f.name.value,
      requirements: [...els.entityRequirementRows.querySelectorAll('.requirement-row')]
        .map(row => ({
          course_id: resolveRequirementCourseId(row),
          sessions_required: Number(row.querySelector('.requirement-count').value || 1),
        }))
        .filter(item => item.course_id),
    };
  }
  if (type === 'course_tag') {
    return { name: f.name.value };
  }
  if (type === 'program') {
    return { code: f.code.value, name: f.name.value };
  }
  if (type === 'course') {
    return {
      code: f.code.value,
      name: f.name.value,
      course_tag_id: Number(els.entityCourseTagSelect.value),
      require_all: !!f.require_all.checked,
      elective: !!f.elective.checked,
    };
  }
  if (type === 'room') {
    return {
      code: f.code.value,
      name: f.name.value,
      capacity: Number(f.capacity.value),
    };
  }
  if (type === 'teacher') {
    return {
      name: f.name.value,
      course_tag_ids: collectCheckedValues(els.entityTeacherTags),
    };
  }
  return {};
}

async function deleteCurrentEntity() {
  const { type, id } = state.editingEntity;
  await deleteEntity(type, id, `Delete this ${type.replace('_', ' ')}?`);
  closeModal('entityModal');
}

async function deleteEntity(type, id, confirmText) {
  if (!confirm(confirmText)) return;
  const res = await fetch(`${CRUD[type]}/${id}`, { method: 'DELETE' });
  const data = await safeJson(res);
  if (!res.ok) {
    alert(formatError(data));
    return;
  }
  state.data = data;
  state.timetableId = state.data.selected_timetable_id || state.timetableId;
  renderContextSelectors();
  renderEntityLists();
  renderBoard();
  renderTeacherLoad();
  populateStaticInputs();
}

function addRequirementRow(courseId = null, sessionsRequired = 1) {
  // Always use the group modal's container if present
  const reqRows = document.getElementById('individualRequirementRows') || els.requirementRows;
  if (!reqRows) return;
  const clone = els.requirementRowTemplate.content.firstElementChild.cloneNode(true);
  const courseInput = clone.querySelector('.requirement-course');
  const datalist = clone.querySelector('datalist#courseOptions');
  // Populate datalist with courses
  datalist.innerHTML = '';
  (state.data.courses || []).filter(c => !c.elective).forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.dataset.courseId = c.id;
    datalist.appendChild(opt);
  });
  if (courseId) {
    const course = (state.data.courses || []).find(c => c.id === courseId);
    courseInput.value = course ? course.name : String(courseId);
  }
  clone.querySelector('.requirement-count').value = sessionsRequired;
  clone.querySelector('.remove-row-btn').addEventListener('click', () => clone.remove());
  reqRows.appendChild(clone);
}

function resolveRequirementCourseId(row) {
  const input = row.querySelector('.requirement-course');
  if (!input) return 0;
  const value = input.value.trim();
  if (!value) return 0;
  const datalist = row.querySelector('datalist#courseOptions');
  if (datalist) {
    const option = Array.from(datalist.querySelectorAll('option')).find(opt => opt.value === value);
    if (option) {
      const id = Number(option.dataset.courseId || option.value);
      return Number.isInteger(id) ? id : 0;
    }
  }
  const numeric = Number(value);
  return Number.isInteger(numeric) ? numeric : 0;
}

function openGroupModal(groupId = null) {
  if (!state.timetableId) {
    alert('Create or select a timetable first.');
    return;
  }
  state.openMenuGroupId = null;
  if (els.groupForm) {
    els.groupForm.reset();
  }
  if (els.requirementRows) {
    els.requirementRows.innerHTML = '';
  }
  renderProgramCheckboxes(els.groupProgramOptions, state.data.programs || [], 'groupPrograms');

  fillSelect(
    els.groupTagSelect,
    (state.data.group_tags || []).map(item => ({ value: item.id, label: `${item.code} — ${item.name}` })),
    true
  );

  if (groupId) {
    const group = (state.data.groups || []).find(item => item.id === groupId);
    if (!group) return;
    state.editingGroupId = groupId;
    els.groupModalTitle.textContent = `Adjust group ${group.code}`;
    els.saveGroupBtn.textContent = 'Save changes';
    els.deleteGroupBtn.classList.remove('hidden');
    els.groupForm.elements.group_id.value = group.id;
    els.groupForm.elements.code.value = group.code;
    els.groupForm.elements.name.value = group.name;
    els.groupForm.elements.group_tag_id.value = group.group_tag.id;
    els.groupForm.elements.capacity.value = group.capacity;
    precheckPrograms(els.groupProgramOptions, group.programs.map(item => item.id));
  } else {
    state.editingGroupId = null;
    els.groupModalTitle.textContent = 'Add group';
    els.saveGroupBtn.textContent = 'Save group';
    els.deleteGroupBtn.classList.add('hidden');
    els.groupForm.elements.capacity.value = 40;
  }

  openModal('groupModal');
}

async function submitGroupForm(event) {
  event.preventDefault();

  if (!state.timetableId) {
    alert('Create or select a timetable first.');
    return;
  }

  const formData = new FormData(els.groupForm);
  const payload = {
    timetable_id: state.timetableId,
    code: formData.get('code'),
    name: formData.get('name') || formData.get('code'),
    group_tag_id: Number(formData.get('group_tag_id')),
    capacity: Number(formData.get('capacity')),
    study_program_ids: els.groupProgramOptions ? collectCheckedValues(els.groupProgramOptions) : [],
    group_requirements: [],
  };

  const isEditing = !!state.editingGroupId;
  const url = isEditing ? `/api/groups/${state.editingGroupId}` : '/api/groups';
  const method = isEditing ? 'PUT' : 'POST';

  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  const data = await safeJson(res);

  if (!res.ok) {
    alert(formatError(data));
    return;
  }

  state.data = data;
  state.timetableId = state.data.selected_timetable_id || state.timetableId;
  closeModal('groupModal');
  renderContextSelectors();
  renderEntityLists();
  renderBoard();
  renderTeacherLoad();
  populateStaticInputs();
}

async function deleteCurrentGroup() {
  if (!state.editingGroupId) return;
  await deleteGroupById(state.editingGroupId);
  closeModal('groupModal');
}

async function deleteGroupById(groupId) {
  const group = (state.data.groups || []).find(item => item.id === groupId);
  if (!group) return;
  if (!confirm(`Delete group ${group.code}? All classes in that group will also be deleted.`)) return;

  const res = await fetch(`/api/groups/${groupId}`, { method: 'DELETE' });
  const data = await safeJson(res);
  if (!res.ok) {
    alert(formatError(data));
    return;
  }
  state.data = data;
  state.timetableId = state.data.selected_timetable_id || state.timetableId;
  state.editingGroupId = null;
  closeModal('groupModal');
  clearSelection(false);
  renderContextSelectors();
  renderEntityLists();
  renderBoard();
  renderTeacherLoad();
  populateStaticInputs();
}

async function openClassModal(classId = null) {
  els.classForm.reset();
  els.classErrors.innerHTML = '';
  let selected = state.selected;
  let editingClass = null;
  if (classId) {
    // Fetch class details from API
    const res = await fetch(`/api/classes/${classId}`);
    if (res.ok) {
      editingClass = await res.json();
      // Set up selection for editing
      selected = [{
        groupId: editingClass.group_id,
        groupCode: editingClass.group_code || '',
        timeslotId: editingClass.timeslot_id,
        slotLabel: editingClass.timeslot_label || ''
      }];
      state.editingClassId = classId;
    } else {
      state.editingClassId = null;
    }
  } else {
    state.editingClassId = null;
  }
  if (!selected.length) return;
  els.classTargetInfo.innerHTML = `<strong>${escapeHtml(selected[0].slotLabel)}</strong><br>${escapeHtml(selected.map(item => item.groupCode).join(', '))}`;
  if (editingClass) {
    els.classModalTitle.textContent = 'Edit class';
    els.classSubmitBtn.textContent = 'Save changes';
    els.classForm.querySelector(`input[name="mode"][value="${editingClass.mode}"]`).checked = true;
  } else {
    els.classModalTitle.textContent = 'Add class';
    els.classSubmitBtn.textContent = 'Create class';
  }
  els.classUpdateWarning?.classList.add('hidden');
  if (editingClass && editingClass.study_program_ids?.length) {
    els.classUpdateWarning?.classList.remove('hidden');
  }
  renderProgramCheckboxes(
    els.classProgramOptions,
    intersectProgramsForSelectedGroups(selected),
    'classPrograms'
  );
  if (editingClass && editingClass.study_program_ids) {
    for (const id of editingClass.study_program_ids) {
      const cb = els.classProgramOptions.querySelector(`input[type="checkbox"][value="${id}"]`);
      if (cb) cb.checked = true;
    }
  }
  els.classProgramOptions.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.addEventListener('change', syncClassFormVisibility));
  renderGroupCheckboxes(els.classGroupOptions, state.data.groups || [], 'classGroups');
  const preselectedGroupIds = editingClass ? [editingClass.group_id] : selected.map(item => item.groupId);
  precheckGroups(els.classGroupOptions, preselectedGroupIds);
  syncClassFormVisibility();
  fillSelect(
    els.roomSelect,
    [{ value: '', label: 'No room' }, ...(state.data.rooms || []).map(r => ({ value: r.id, label: `${r.code} (${r.capacity})` }))],
    false
  );
  // Pre-fill form if editing
  if (editingClass) {
    els.courseSelect.value = editingClass.course_id;
    els.teacherSelect.value = editingClass.teacher_id || '';
    els.roomSelect.value = editingClass.room_id || '';
    els.classForm.elements['expected_size'].value = editingClass.expected_size || '';
    els.classForm.elements['notes'].value = editingClass.notes || '';
  }
  openModal('classModal');
}

function intersectProgramsForSelectedGroups(selected = state.selected) {
  if (!selected.length) return [];
  const selectedGroups = (state.data.groups || []).filter(group => selected.some(sel => sel.groupId === group.id));
  if (!selectedGroups.length) return [];
  let set = new Set(selectedGroups[0].programs.map(p => p.id));
  selectedGroups.slice(1).forEach(group => {
    set = new Set(group.programs.map(p => p.id).filter(id => set.has(id)));
  });
  return (state.data.programs || []).filter(p => set.has(p.id));
}

function syncClassFormVisibility() {
  const mode = els.classForm.querySelector('input[name="mode"]:checked').value;
  let courses = state.data.courses || [];
  let filteredByProgram = false;

  const selectedProgramIds = collectCheckedValues(els.classProgramOptions);
  if (mode === 'program') {
    if (selectedProgramIds.length > 0) {
      filteredByProgram = true;
      const programCourseIds = new Set();
      selectedProgramIds.forEach(programId => {
        const program = (state.data.programs || []).find(p => p.id === programId);
        if (program && program.requirements) {
          program.requirements.forEach(req => programCourseIds.add(req.course_id));
        }
      });
      if (programCourseIds.size > 0) {
        courses = courses.filter(c => programCourseIds.has(c.id));
      }
    }
  }

  if (!filteredByProgram && state.selected && state.selected.length > 0 && mode !== 'elective') {
    // Only show courses required by the selected group(s) for non-elective modes.
    const requiredCourseIds = new Set();
    state.selected.forEach(sel => {
      const group = (state.data.groups || []).find(g => g.id === sel.groupId);
      if (group && group.requirements) {
        group.requirements.forEach(req => requiredCourseIds.add(req.course_id));
      }
    });
    if (requiredCourseIds.size > 0) {
      courses = courses.filter(c => requiredCourseIds.has(c.id));
    }
  }

  // Filter by mode as before
  courses = courses.filter(course => {
    if (mode === 'required_all') return course.require_all;
    if (mode === 'program') return !course.require_all && !course.elective;
    return course.elective;
  });

  const allowProgramMode = selectedProgramIds.length > 0;
  fillSelect(els.courseSelect, courses.map(c => ({ value: c.id, label: c.name })), true);

  const showProgramSelection = mode !== 'required_all';
  els.programSelectionBox.classList.toggle('hidden', !showProgramSelection);
  els.programClassHint.classList.toggle('hidden', !(mode === 'program' && !allowProgramMode));
  els.courseSelect.disabled = mode === 'program' && !allowProgramMode;
  els.groupSelectionBox.classList.toggle('hidden', mode === 'required_all');
  if (mode !== 'required_all') {
    updateClassGroupOptions();
  }
  els.classForm.querySelectorAll('input[name="mode"]').forEach(radio => {
    if (radio.value === 'program') {
      radio.disabled = false;
    }
  });
  updateTeacherOptions();
  els.courseSelect.onchange = updateTeacherOptions;
}

function validateClassModeSelection() {
  const mode = els.classForm.querySelector('input[name="mode"]:checked').value;
  const selectedProgramIds = collectCheckedValues(els.classProgramOptions);
  const selectedGroupIds = getClassGroupIds();
  if (mode === 'program') {
    if (!selectedProgramIds.length) {
      alert('Check at least one study program to configure a Study program class.');
      return false;
    }
    if (!selectedGroupIds.length && (!state.selected || !state.selected.length)) {
      alert('Select at least one group or choose groups in the form for a Study program class.');
      return false;
    }
  }
  if (mode === 'elective') {
    if (!selectedGroupIds.length && !selectedProgramIds.length && (!state.selected || !state.selected.length)) {
      alert('Select at least one group or program for this elective class.');
      return false;
    }
  }
  return true;
}

function updateTeacherOptions() {
  const courseId = Number(els.courseSelect.value);
  const course = (state.data.courses || []).find(c => c.id === courseId);
  let teachers = state.data.teachers || [];
  if (course) {
    const allowedIds = (state.data.teacher_ids_by_tag || {})[course.course_tag_id] || [];
    if (allowedIds.length) {
      teachers = teachers.filter(t => allowedIds.includes(t.id));
    }
  }
  fillSelect(
    els.teacherSelect,
    [{ value: '', label: 'No teacher' }, ...teachers.map(t => ({ value: t.id, label: t.name }))],
    false
  );
}

async function submitClassForm(event) {
  event.preventDefault();
  const formData = new FormData(els.classForm);
  const mode = formData.get('mode');
  let selected = state.selected;
  if (state.editingClassId) {
    // If editing, use the selection from the class being edited
    const editingClass = await (await fetch(`/api/classes/${state.editingClassId}`)).json();
    selected = [{
      groupId: editingClass.group_id,
      groupCode: editingClass.group_code || '',
      timeslotId: editingClass.timeslot_id,
      slotLabel: editingClass.timeslot_label || ''
    }];
  }
  const selectedGroupIds = getClassGroupIds();
  const selectedProgramIds = collectCheckedValues(els.classProgramOptions);
  let targetGroupIds = selectedGroupIds.length ? selectedGroupIds.slice() : selected.map(item => item.groupId);
  if (mode === 'elective' && selectedProgramIds.length > 0) {
    const programGroupIds = (state.data.groups || [])
      .filter(group => selectedProgramIds.some(pid => group.programs.some(p => p.id === pid)))
      .map(group => group.id);
    targetGroupIds = Array.from(new Set([...targetGroupIds, ...programGroupIds]));
  }
  if ((mode === 'program' || mode === 'elective') && !targetGroupIds.length) {
    targetGroupIds = selected.map(item => item.groupId);
  }
  const payload = {
    timeslot_id: selected[0].timeslotId,
    target_group_ids: targetGroupIds,
    mode,
    course_id: Number(formData.get('course_id')),
    teacher_id: toNullableNumber(formData.get('teacher_id')),
    room_id: toNullableNumber(formData.get('room_id')),
    study_program_ids: mode === 'program' ? selectedProgramIds : [],
    expected_size: toNullableNumber(formData.get('expected_size')),
    notes: formData.get('notes') || null,
  };
  if (!validateClassModeSelection()) return;
  // For study program class, allow same teacher in same slot for different groups
  let allowTeacherConflict = false;
  if (payload.mode === 'program') {
    allowTeacherConflict = true;
  }
  let url = '/api/classes';
  let method = 'POST';
  if (state.editingClassId) {
    url = `/api/classes/${state.editingClassId}`;
    method = 'PUT';
  }
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, allow_teacher_conflict: allowTeacherConflict }),
  });
  const data = await safeJson(res);
  if (!res.ok || !data.ok) {
    // If error is only about teacher conflict and allowTeacherConflict is true, ignore it
    if (allowTeacherConflict && data.errors && data.errors.some(e => String(e).toLowerCase().includes('teacher conflict'))) {
      // proceed as if success
    } else {
      const errors = data.errors || [formatError(data)];
      els.classErrors.innerHTML = errors.map(err => `<div>${escapeHtml(err)}</div>`).join('');
      return;
    }
  }
  state.data = (data.bootstrap || data);
  state.timetableId = state.data.selected_timetable_id || state.timetableId;
  closeModal('classModal');
  clearSelection(false);
  state.editingClassId = null;
  renderContextSelectors();
  renderEntityLists();
  renderBoard();
  renderTeacherLoad();
  populateStaticInputs();
}

function renderProgramCheckboxes(container, items, groupName, labelKey = 'code') {
  if (!container) return;
  container.innerHTML = '';
  items.forEach(item => {
    const label = document.createElement('label');
    label.className = 'checkbox-card';
    label.innerHTML = `<input type="checkbox" name="${groupName}" value="${item.id}" /><span>${escapeHtml(item[labelKey])}</span>`;
    container.appendChild(label);
  });
}

function renderGroupCheckboxes(container, groups, groupName, disabledGroupIds = new Set()) {
  if (!container) return;
  container.innerHTML = '';
  groups.forEach(group => {
    const disabled = disabledGroupIds.has(group.id);
    const label = document.createElement('label');
    label.className = 'checkbox-card';
    label.innerHTML = `<input type="checkbox" name="${groupName}" value="${group.id}" ${disabled ? 'disabled' : ''} /><span>${escapeHtml(group.code + (group.name ? ` — ${group.name}` : ''))}</span>`;
    container.appendChild(label);
  });
}

function precheckPrograms(container, ids) {
  if (!container) return;
  const set = new Set(ids);
  [...container.querySelectorAll('input[type="checkbox"]')].forEach(input => {
    input.checked = set.has(Number(input.value));
  });
}

function precheckGroups(container, ids) {
  if (!container) return;
  const set = new Set(ids);
  [...container.querySelectorAll('input[type="checkbox"]')].forEach(input => {
    input.checked = set.has(Number(input.value));
  });
}

function getClassGroupIds() {
  if (!els.classGroupOptions) return [];
  return [...els.classGroupOptions.querySelectorAll('input[type="checkbox"]:checked')].map(input => Number(input.value));
}

function allGroupsForPrograms(programIds) {
  if (!programIds.length) return [];
  return (state.data.groups || [])
    .filter(group => programIds.every(pid => group.programs.some(p => p.id === pid)))
    .map(group => group.id);
}

function updateClassGroupOptions() {
  if (!els.classGroupOptions || !els.classForm) return;
  const mode = els.classForm.querySelector('input[name="mode"]:checked')?.value;
  const selectedProgramIds = collectCheckedValues(els.classProgramOptions);
  const disabledGroupIds = new Set(
    (state.data.groups || [])
      .filter(group => mode === 'program' && selectedProgramIds.length > 0 && !selectedProgramIds.every(pid => group.programs.some(p => p.id === pid)))
      .map(group => group.id)
  );
  const currentlyChecked = getClassGroupIds();
  renderGroupCheckboxes(els.classGroupOptions, (state.data.groups || []), 'classGroups', disabledGroupIds);
  const selectedGroupIds = currentlyChecked.length
    ? currentlyChecked.filter(id => !disabledGroupIds.has(id))
    : state.selected.map(item => item.groupId).filter(id => !disabledGroupIds.has(id));
  precheckGroups(els.classGroupOptions, selectedGroupIds);
}

function fillSelect(selectEl, options, includePlaceholder = false) {
  selectEl.innerHTML = '';
  if (includePlaceholder) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Select...';
    selectEl.appendChild(opt);
  }
  options.forEach(option => {
    const opt = document.createElement('option');
    opt.value = option.value;
    opt.textContent = option.label;
    selectEl.appendChild(opt);
  });
}

function collectCheckedValues(container) {
  return [...container.querySelectorAll('input[type="checkbox"]:checked')].map(input => Number(input.value));
}

function openModal(id) {
  document.getElementById(id).classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

function toNullableNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

async function safeJson(res) {
  try {
    return await res.json();
  } catch {
    return {};
  }
}

function formatError(data) {
  if (!data) return 'Unknown error';
  const detail = data.detail ?? data;
  if (Array.isArray(detail)) {
    return detail.map(err => {
      if (typeof err === 'string') return err;
      const loc = Array.isArray(err.loc) ? err.loc.join('.') : '';
      return `${loc} - ${err.msg || JSON.stringify(err)}`;
    }).join('\n');
  }
  if (typeof detail === 'object') {
    return JSON.stringify(detail, null, 2);
  }
  return String(detail);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function openExportProgramModal() {
  if (!els.exportProgramModal || !els.exportProgramOptions) return;
  if (!els.exportProgramOptions.querySelector('input[type="checkbox"]')) {
    alert('No study programs available to export.');
    return;
  }
  openModal('exportProgramModal');
}

async function submitExportProgramForm(e) {
  e.preventDefault();
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  const programIds = collectCheckedValues(els.exportProgramOptions);
  if (!programIds.length) {
    alert('Select at least one study program.');
    return;
  }
  const params = programIds.map(id => `program_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  closeModal('exportProgramModal');
  await downloadExcel(url, 'Exporting program...');
}

async function downloadExcel(url, busyText = 'Exporting...') {
  if (!url) return;
  const exportAnchor = els.exportBtn;
  const prevText = exportAnchor?.textContent;
  const wasDisabled = exportAnchor?.disabled;
  if (exportAnchor) {
    exportAnchor.disabled = true;
    exportAnchor.textContent = busyText;
  }
  try {
    const res = await fetch(url, { method: 'GET' });
    if (!res.ok) {
      const data = await safeJson(res);
      alert('Cannot export: ' + formatError(data));
      return;
    }
    const disposition = res.headers.get('content-disposition') || res.headers.get('Content-Disposition');
    let filename = res.headers.get('x-download-filename') || res.headers.get('X-Download-Filename') || 'timetable.xlsx';
    if (disposition && disposition.includes('filename=')) {
      filename = disposition.split('filename=')[1].replace(/['"]/g, '').trim();
    } else if (!filename || filename === 'timetable.xlsx') {
      const urlObj = new URL(url, window.location.href);
      const pathname = urlObj.pathname.split('/').pop() || 'timetable.xlsx';
      filename = pathname.endsWith('.xlsx') ? pathname : 'timetable.xlsx';
    }
    filename = filename.replace(/[\\/:*?"<>|]/g, '_');
    const blob = await res.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = filename;
    a.type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      window.URL.revokeObjectURL(downloadUrl);
      a.remove();
    }, 100);
  } finally {
    if (exportAnchor) {
      exportAnchor.disabled = wasDisabled;
      exportAnchor.textContent = prevText;
    }
  }
}

function openGroupOnlyRequirementModal() {
  if (!els.groupOnlyRequirementModal) return;
  if (!els.groupOnlyRequirementGroupSelect || !els.groupOnlyRequirementCourseSelect) return;
  els.groupOnlyRequirementGroupSelect.innerHTML = '';
  (state.data.groups || []).forEach(group => {
    const opt = document.createElement('option');
    opt.value = group.id;
    opt.textContent = `${group.code} — ${group.name}`;
    els.groupOnlyRequirementGroupSelect.appendChild(opt);
  });
  els.groupOnlyRequirementCourseSelect.innerHTML = '';
  (state.data.courses || []).filter(c => !c.elective).forEach(course => {
    const opt = document.createElement('option');
    opt.value = course.id;
    opt.textContent = course.name;
    els.groupOnlyRequirementCourseSelect.appendChild(opt);
  });
  setSelectValues(els.groupOnlyRequirementGroupSelect, []);
  els.groupOnlyRequirementCourseSelect.value = '';
  els.groupOnlyRequirementSessionsInput.value = 1;
  delete els.groupOnlyRequirementModal.dataset.editingRequirementId;
  openModal('groupOnlyRequirementModal');
}

function openEditGroupOnlyRequirementModal(req) {
  openGroupOnlyRequirementModal();
  setSelectValues(els.groupOnlyRequirementGroupSelect, [req.group_id]);
  els.groupOnlyRequirementCourseSelect.value = req.course_id;
  els.groupOnlyRequirementSessionsInput.value = req.sessions_required || 1;
  els.groupOnlyRequirementModal.dataset.editingRequirementId = req.id;
  els.groupOnlyRequirementModal.querySelector('#groupOnlyRequirementModalTitle').textContent = 'Edit group-only requirement';
}

async function submitGroupOnlyRequirementForm(e) {
  e.preventDefault();
  const groupIds = getSelectValues(els.groupOnlyRequirementGroupSelect);
  const courseId = Number(els.groupOnlyRequirementCourseSelect.value);
  const sessions = Number(els.groupOnlyRequirementSessionsInput.value) || 1;
  if (!groupIds.length || !courseId) {
    alert('Select at least one group and a course.');
    return;
  }

  const payload = { group_ids: groupIds, course_id: courseId, sessions_required: sessions };
  let url = '/api/group-only-requirements';
  let method = 'POST';
  if (els.groupOnlyRequirementModal.dataset.editingRequirementId) {
    url = `/api/group-only-requirements/${els.groupOnlyRequirementModal.dataset.editingRequirementId}`;
    method = 'PATCH';
  }

  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert('Failed to add group-only requirement');
    return;
  }
  closeModal('groupOnlyRequirementModal');
  await refreshData(state.timetableId);
}

async function deleteGroupOnlyRequirement(requirementId) {
  if (!confirm('Delete this group-only requirement?')) return;
  const res = await fetch(`/api/group-only-requirements/${requirementId}`, { method: 'DELETE' });
  if (!res.ok) {
    alert('Failed to delete group-only requirement');
    return;
  }
  await refreshData(state.timetableId);
}

function openAddRequirementModal(type) {
  console.log('openAddRequirementModal called with type:', type);
  if (!els.addRequirementModal) {
    console.warn('addRequirementModal not found');
    return;
  }
  els.addRequirementModalTitle.textContent = type === 'group_tag' ? 'Add Group Tag Requirement' : 'Add Study Program Requirement';
  els.requirementTagOrProgramText.textContent = type === 'group_tag' ? 'Group Tag(s)' : 'Study Program(s)';
  els.requirementTagOrProgramSelect.innerHTML = '';
  const items = type === 'group_tag' ? (state.data.group_tags || []) : (state.data.programs || []);
  items.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item.id;
    opt.textContent = `${item.code} — ${item.name}`;
    els.requirementTagOrProgramSelect.appendChild(opt);
  });
  els.requirementCourseSelect.innerHTML = '';
  (state.data.courses || []).forEach(course => {
    const opt = document.createElement('option');
    opt.value = course.id;
    opt.textContent = course.name;
    els.requirementCourseSelect.appendChild(opt);
  });
  setSelectValues(els.requirementTagOrProgramSelect, []);
  els.requirementCourseSelect.value = '';
  els.requirementSessionsInput.value = 1;
  if (els.requirementSessionsRow) {
    els.requirementSessionsRow.classList.remove('hidden');
  }
  if (els.requirementSessionsInput) {
    els.requirementSessionsInput.required = true;
  }
  els.addRequirementModal.dataset.type = type;
  delete els.addRequirementModal.dataset.editingType;
  delete els.addRequirementModal.dataset.editingTargetId;
  openModal('addRequirementModal');
}

function openEditRequirementModal(type, targetId, courseId, sessionsRequired) {
  openAddRequirementModal(type);
  els.addRequirementModalTitle.textContent = type === 'group_tag' ? 'Edit Group Tag Requirement' : 'Edit Study Program Requirement';
  setSelectValues(els.requirementTagOrProgramSelect, [targetId]);
  els.requirementCourseSelect.value = courseId;
  els.requirementSessionsInput.value = sessionsRequired || 1;
}

async function submitAddRequirementForm(e) {
  e.preventDefault();
  const type = els.addRequirementModal.dataset.type || 'group_tag';
  const targetIds = getSelectValues(els.requirementTagOrProgramSelect);
  const courseId = Number(els.requirementCourseSelect.value);
  const sessions = Number(els.requirementSessionsInput.value) || 1;
  if (!targetIds.length) {
    alert(`Select at least one ${type === 'group_tag' ? 'group tag' : 'study program'}.`);
    return;
  }
  if (!courseId) {
    alert('Select a course.');
    return;
  }

  const payload = { course_id: courseId, timetable_id: state.timetableId, sessions_required: sessions };
  const requests = targetIds.map(targetId => {
    let url = '';
    let body = { ...payload };
    if (type === 'group_tag') {
      url = `/api/group-tags/${targetId}/requirements`;
    } else {
      url = `/api/study-programs/${targetId}/requirements`;
    }
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  });

  const results = await Promise.all(requests);
  const failed = results.find(res => !res.ok);
  if (failed) {
    const data = await failed.json().catch(() => ({}));
    alert(`Failed to add requirement: ${data.detail || failed.statusText}`);
    return;
  }
  closeModal('addRequirementModal');
  await refreshData(state.timetableId);
}

async function deleteRequirement(type, tagOrProgId, courseId) {
  let url = '';
  if (type === 'group_tag') {
    url = `/api/group-tags/${tagOrProgId}/requirements/${courseId}`;
  } else {
    url = `/api/study-programs/${tagOrProgId}/requirements/${courseId}`;
  }
  if (!confirm('Delete this requirement?')) return;
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) {
    alert('Failed to delete requirement');
    return;
  }
  await refreshData(state.timetableId);
}