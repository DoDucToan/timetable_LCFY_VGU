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

async function refreshData(timetableId = null, cycleId = null) {
  try {
    let url = '/api/bootstrap';
    const params = [];
    if (timetableId != null) {
      params.push(`timetable_id=${timetableId}`);
    }
    if (cycleId != null) {
      params.push(`cycle_id=${cycleId}`);
    }
    if (params.length) {
      url += `?${params.join('&')}`;
    }
    const res = await fetch(url);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      alert('Failed to load data: ' + (data.detail || res.statusText));
      return;
    }
    const data = await res.json();
    state.data = data;
    if (state.selectedCycleId == null && typeof data.selected_cycle_id !== 'undefined') {
      state.selectedCycleId = data.selected_cycle_id;
    }
    if (timetableId == null && data.selected_timetable_id) {
      state.timetableId = data.selected_timetable_id;
    }
    state.selected = [];
    state.selectedGroupIds.clear();
    if (els.deleteSelectedGroupsBtn) {
      els.deleteSelectedGroupsBtn.disabled = true;
    }
    renderContextSelectors();
    renderEntityLists();
    renderColorSettings();
    renderColorLegend();
    renderBoard();
    renderTeacherLoad();
    populateStaticInputs();
    renderRequirementsSection();
    refreshRequirementsModalIfOpen();
    checkExportAllowed();
  } catch (err) {
    alert('Error loading data: ' + err);
  }
}

function renderRequirementsSection() {
  const groupTagRoot = document.getElementById('groupTagRequirementsSummary');
  const programRoot = document.getElementById('programRequirementsSummary');
  const groupOnlyRoot = document.getElementById('groupOnlyRequirementsSummary');
  if (!groupTagRoot || !programRoot || !groupOnlyRoot) return;

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

  groupOnlyRoot.innerHTML = `<button type="button" class="ghost-btn" data-view-requirements="group_only">Group-only requirements (${groupOnlyRequirements.length})</button>`;
  groupTagRoot.innerHTML = `<button type="button" class="ghost-btn" data-view-requirements="group_tag">Group tag requirements (${groupTagRequirements.length})</button>`;
  programRoot.innerHTML = `<button type="button" class="ghost-btn" data-view-requirements="program">Study program requirements (${programRequirements.length})</button>`;
}

function openViewRequirementsModal(type) {
  if (!els.viewRequirementsModal) return;
  state.activeRequirementModalType = type;
  const titleMap = {
    group_only: 'Group-only requirements',
    group_tag: 'Group tag requirements',
    program: 'Study program requirements',
  };
  const title = titleMap[type] || 'Requirements';
  const titleEl = document.getElementById('viewRequirementsModalTitle');
  if (titleEl) titleEl.textContent = title;
  renderRequirementsModal(type);
  openModal('viewRequirementsModal');
}

function renderRequirementsModal(type) {
  if (!els.viewRequirementsContent) return;
  const root = els.viewRequirementsContent;
  root.innerHTML = '';

  const formatCourseName = req => req.course_name || req.course_id || 'Unknown course';
  const table = document.createElement('table');
  table.className = 'requirements-modal-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th>Item</th>
        <th>Requirement</th>
        <th></th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector('tbody');

  const addGroupSection = (label, items) => {
    const headerRow = document.createElement('tr');
    headerRow.className = 'requirements-table-group';
    const headerCell = document.createElement('td');
    headerCell.colSpan = 3;
    headerCell.textContent = label;
    headerRow.appendChild(headerCell);
    tbody.appendChild(headerRow);

    items.forEach(item => {
      const row = document.createElement('tr');
      row.className = 'requirements-table-item-row';
      const labelCell = document.createElement('td');
      labelCell.textContent = '';
      const detailCell = document.createElement('td');
      detailCell.textContent = item.detail;
      const actionCell = document.createElement('td');
      actionCell.className = 'requirements-table-action-cell';
      if (item.editHandler) {
        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'ghost-btn small';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', item.editHandler);
        actionCell.appendChild(editBtn);
      }
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'danger-btn small';
      deleteBtn.textContent = 'Delete';
      deleteBtn.addEventListener('click', item.deleteHandler);
      actionCell.appendChild(deleteBtn);
      row.appendChild(labelCell);
      row.appendChild(detailCell);
      row.appendChild(actionCell);
      tbody.appendChild(row);
    });
  };

  let added = false;
  if (type === 'group_only') {
    (state.data.groups || []).forEach(group => {
      const items = (group.group_requirements || []).map(req => ({
        detail: `${formatCourseName(req)} · ${req.sessions_required || 1} session(s)`,
        deleteHandler: () => deleteGroupOnlyRequirement(req.id),
        editHandler: () => openEditGroupOnlyRequirementModal(req),
      }));
      if (items.length) {
        addGroupSection(`${group.code} — ${group.name}`, items);
        added = true;
      }
    });
    if (!added) root.innerHTML = '<div class="muted">No group-only requirements.</div>';
    else root.appendChild(table);
    return;
  }

  if (type === 'group_tag') {
    (state.data.group_tags || []).forEach(tag => {
      const items = (tag.requirements || []).map(req => ({
        detail: `${formatCourseName(req)} · ${req.sessions_required || 1} session(s)`,
        deleteHandler: () => deleteRequirement('group_tag', tag.id, req.course_id),
        editHandler: () => openEditRequirementModal('group_tag', tag.id, req.course_id, req.sessions_required),
      }));
      if (items.length) {
        addGroupSection(`${tag.code} — ${tag.name}`, items);
        added = true;
      }
    });
    if (!added) root.innerHTML = '<div class="muted">No group tag requirements.</div>';
    else root.appendChild(table);
    return;
  }

  if (type === 'program') {
    (state.data.programs || []).forEach(prog => {
      const items = (prog.requirements || []).map(req => ({
        detail: `${formatCourseName(req)} · ${req.sessions_required || 1} session(s)`,
        deleteHandler: () => deleteRequirement('program', prog.id, req.course_id),
        editHandler: () => openEditRequirementModal('program', prog.id, req.course_id, req.sessions_required),
      }));
      if (items.length) {
        addGroupSection(`${prog.code} — ${prog.name}`, items);
        added = true;
      }
    });
    if (!added) root.innerHTML = '<div class="muted">No study program requirements.</div>';
    else root.appendChild(table);
    return;
  }

  root.innerHTML = '<div class="muted">No requirements available.</div>';
}

function refreshRequirementsModalIfOpen() {
  if (!els.viewRequirementsModal || !state.activeRequirementModalType) return;
  if (els.viewRequirementsModal.classList.contains('hidden')) return;
  renderRequirementsModal(state.activeRequirementModalType);
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
  selectedCycleId: null,
  selected: [],
  selectedGroupIds: new Set(),
  selectedTeacherCourseTagIds: new Set(),
  editingGroupId: null,
  openMenuGroupId: null,
  selectedProgramGroupId: null,
  editingEntity: { type: null, id: null },
  activeRequirementModalType: null,
};

let currentImportEntity = null;
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
  initTeacherFilterFromQuery();
  const pathMatch = window.location.pathname.match(/^\/cycle\/(\d+)\/?$/);
  if (pathMatch) {
    state.selectedCycleId = Number(pathMatch[1]);
    refreshData(null, state.selectedCycleId);
  } else if (state.selectedCycleId != null) {
    refreshData(null, state.selectedCycleId);
  } else {
    refreshData();
  }
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
    'duplicateCycleBtn',
    'deleteCycleBtn',
    'editTimetableBtn',
    'deleteTimetableBtn',
    'deleteSelectedGroupsBtn',
    'exportBtn',
    'exportProgramBtn',
    'exportGroupBtn',
    'exportAllGroupBtn',
    'exportCourseBtn',
    'exportAllCourseBtn',
    'exportTeacherBtn',
    'exportAllTeacherBtn',
    'exportProgramModal',
    'exportProgramForm',
    'exportProgramOptions',
    'exportGroupModal',
    'exportGroupForm',
    'exportGroupOptions',
    'exportGroupTagBtn',
    'exportGroupTagModal',
    'exportGroupTagForm',
    'exportGroupTagOptions',
    'exportTeacherModal',
    'exportTeacherForm',
    'exportTeacherOptions',
    'exportCourseModal',
    'exportCourseForm',
    'exportCourseOptions',
    'teacherScheduleModal',
    'teacherScheduleModalTitle',
    'teacherScheduleTableWrapper',
    'groupScheduleModal',
    'groupScheduleModalTitle',
    'groupScheduleTableWrapper',
    'groupTagList',
    'courseTagList',
    'programList',
    'roomList',
    'teacherFilterWrapper',
    'teacherCourseTagFilter',
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
    'entityUploadInput',
    'entityUploadMessage',
    'entityModalTitle',
    'entityDeleteBtn',
    'entityErrors',
    'entityCycleSelect',
    'entityCourseTagSelect',
    'entityFillColorInput',
    'entityTeacherTags',
    'entityCoursePrograms',
    'entityRequirementRows',
    'viewRequirementsModal',
    'viewRequirementsContent',
    'addEntityRequirementBtn',
    'addGroupTagRequirementPanelBtn',
    'addStudyProgramRequirementPanelBtn',
    'addGroupOnlyRequirementPanelBtn',
    'addGroupTagRequirementBtn',
    'addStudyProgramRequirementBtn',
  ].forEach(id => {
    els[id] = document.getElementById(id);
  });
  els.addTimetableBtn = document.querySelector('[data-open-entity="timetable"]');
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
  }
  if (els.refreshBtn) {
    els.refreshBtn.addEventListener('click', refreshData);
  }
  if (els.exportProgramBtn) {
    els.exportProgramBtn.addEventListener('click', openExportProgramModal);
  }
  if (els.exportGroupBtn) {
    els.exportGroupBtn.addEventListener('click', openExportGroupModal);
  }
  if (els.exportGroupTagBtn) {
    els.exportGroupTagBtn.addEventListener('click', openExportGroupTagModal);
  }
  if (els.exportAllGroupBtn) {
    els.exportAllGroupBtn.addEventListener('click', openExportAllGroup);
  }
  if (els.exportCourseBtn) {
    els.exportCourseBtn.addEventListener('click', openExportCourseModal);
  }
  if (els.exportAllCourseBtn) {
    els.exportAllCourseBtn.addEventListener('click', openExportAllCourse);
  }
  if (els.exportTeacherBtn) {
    els.exportTeacherBtn.addEventListener('click', openExportTeacherModal);
  }
  if (els.exportAllTeacherBtn) {
    els.exportAllTeacherBtn.addEventListener('click', openExportAllTeacher);
  }
  if (els.exportProgramForm) {
    els.exportProgramForm.addEventListener('submit', submitExportProgramForm);
  }
  if (els.exportGroupForm) {
    els.exportGroupForm.addEventListener('submit', submitExportGroupForm);
  }
  if (els.exportGroupTagForm) {
    els.exportGroupTagForm.addEventListener('submit', submitExportGroupTagForm);
  }
  if (els.exportTeacherForm) {
    els.exportTeacherForm.addEventListener('submit', submitExportTeacherForm);
  }
  if (els.exportCourseForm) {
    els.exportCourseForm.addEventListener('submit', submitExportCourseForm);
  }

  const importButtons = {
    teachers: {
      download: document.getElementById('downloadTeacherTemplateBtn'),
      upload: document.getElementById('uploadTeacherTemplateBtn'),
    },
    'study-programs': {
      download: document.getElementById('downloadProgramTemplateBtn'),
      upload: document.getElementById('uploadProgramTemplateBtn'),
    },
    'course-tags': {
      download: document.getElementById('downloadCourseTagTemplateBtn'),
      upload: document.getElementById('uploadCourseTagTemplateBtn'),
    },
    rooms: {
      download: document.getElementById('downloadRoomTemplateBtn'),
      upload: document.getElementById('uploadRoomTemplateBtn'),
    },
    courses: {
      download: document.getElementById('downloadCourseTemplateBtn'),
      upload: document.getElementById('uploadCourseTemplateBtn'),
    },
    'group-tags': {
      download: document.getElementById('downloadGroupTagTemplateBtn'),
      upload: document.getElementById('uploadGroupTagTemplateBtn'),
    },
    groups: {
      download: document.getElementById('downloadGroupTemplateBtn'),
      upload: document.getElementById('uploadGroupTemplateBtn'),
    },
    requirements: {
      download: document.getElementById('downloadRequirementTemplateBtn'),
      upload: document.getElementById('uploadRequirementTemplateBtn'),
    },
  };

  Object.entries(importButtons).forEach(([entity, buttons]) => {
    if (buttons.download) {
      buttons.download.addEventListener('click', () => downloadTemplate(entity));
    }
    if (buttons.upload) {
      buttons.upload.addEventListener('click', () => openUploadDialog(entity));
    }
  });

  const currentDataUploadButtons = {
    teachers: document.getElementById('uploadTeachersCurrentBtn'),
    'study-programs': document.getElementById('uploadStudyProgramsCurrentBtn'),
    'course-tags': document.getElementById('uploadCourseTagsCurrentBtn'),
    rooms: document.getElementById('uploadRoomsCurrentBtn'),
    courses: document.getElementById('uploadCoursesCurrentBtn'),
    'group-tags': document.getElementById('uploadGroupTagsCurrentBtn'),
    groups: document.getElementById('uploadGroupsCurrentBtn'),
    requirements: document.getElementById('uploadRequirementsCurrentBtn'),
  };

  Object.entries(currentDataUploadButtons).forEach(([entity, button]) => {
    if (button) {
      button.addEventListener('click', () => openUploadDialog(entity));
    }
  });

  if (els.entityUploadInput) {
    els.entityUploadInput.addEventListener('change', handleEntityUpload);
  }

  if (els.deleteSelectedGroupsBtn) {
    els.deleteSelectedGroupsBtn.addEventListener('click', deleteSelectedGroups);
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
    const type = btn.dataset.openEntity;
    if (type) {
      btn.addEventListener('click', () => openEntityModal(type));
    }
  });

  document.body.addEventListener('click', event => {
    const openEntityTarget = event.target.closest('[data-open-entity]');
    if (openEntityTarget) {
      const type = openEntityTarget.dataset.openEntity;
      if (type) {
        event.preventDefault();
        openEntityModal(type);
        return;
      }
    }
    const viewReqTarget = event.target.closest('[data-view-requirements]');
    if (viewReqTarget) {
      event.preventDefault();
      openViewRequirementsModal(viewReqTarget.dataset.viewRequirements);
      return;
    }
  });

  document.querySelectorAll('[data-jump]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = document.querySelector(btn.dataset.jump);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  let initialPage = {};
  const initialPageData = document.getElementById('initial-page-data');
  if (initialPageData && initialPageData.textContent) {
    try {
      initialPage = JSON.parse(initialPageData.textContent);
    } catch {
      initialPage = {};
    }
  }
  if (typeof initialPage.selectedCycleId !== 'undefined' && initialPage.selectedCycleId !== null) {
    state.selectedCycleId = initialPage.selectedCycleId;
  }
  if (initialPage.activeSection) {
    const sectionMap = {
      'teachers': '#teachersSection',
      'rooms': '#roomsSection',
      'courses': '#coursesSection',
      'study-programs': '#programsSection',
      'course-tags': '#courseTagsSection',
      'group-tags': '#groupTagsSection',
      'colors': '#colorsSection',
      'upload': '#uploadSection',
    };
    const target = document.querySelector(sectionMap[initialPage.activeSection]);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    if (initialPage.openNew) {
      const entityTypeMap = {
        'teachers': 'teacher',
        'rooms': 'room',
        'courses': 'course',
        'study-programs': 'program',
        'course-tags': 'course_tag',
        'group-tags': 'group_tag',
      };
      const entityType = entityTypeMap[initialPage.activeSection];
      if (entityType) {
        openEntityModal(entityType);
      }
    }
  }

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
  if (els.courseSelect) {
    els.courseSelect.addEventListener('change', () => {
      window.clearTimeout(state.courseSelectTimer);
      state.courseSelectTimer = window.setTimeout(() => {
        const courseId = Number(els.courseSelect.value) || null;
        updateTeacherOptions(null, null, courseId);
        updateRoomOptions(null, null, courseId);
      }, 100);
    });
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
  if (els.duplicateCycleBtn) {
    els.duplicateCycleBtn.addEventListener('click', async () => {
      const id = toNullableNumber(els.cycleSelect.value);
      if (!id) return;
      if (!confirm('Duplicate this cycle and its timetable?')) return;
      const res = await fetch(`/api/cycles/${id}/duplicate`, { method: 'POST' });
      const data = await safeJson(res);
      if (!res.ok) {
        alert(formatError(data));
        return;
      }
      state.data = data;
      state.selectedCycleId = data.selected_cycle_id;
      state.timetableId = data.selected_timetable_id;
      if (data.selected_cycle_id) {
        window.location.href = `/cycle/${data.selected_cycle_id}`;
      } else {
        refreshData();
      }
    });
  } else {
    console.warn('Missing element: duplicateCycleBtn');
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
  const selectedCycleId = state.selectedCycleId ?? (state.data.cycles?.length ? state.data.cycles[0].id : null);

  if (els.cycleSelect) {
    fillSelect(
      els.cycleSelect,
      (state.data.cycles || []).map(item => ({ value: item.id, label: `${item.name} (${item.year_starting})` })),
      true
    );
    if (selectedCycleId) {
      els.cycleSelect.value = String(selectedCycleId);
    }
  }

  // Debug log
  console.log('renderContextSelectors: timetables', state.data.timetables);
  const timetableOptions = (state.data.timetables || [])
    .filter(item => !selectedCycleId || item.cycle_id === Number(selectedCycleId))
    .map(item => ({
      value: item.id,
      label: `Timetable #${item.id}`,
    }));

  if (els.timetableSelect) {
    fillSelect(els.timetableSelect, timetableOptions, true);
    if (state.timetableId && timetableOptions.some(item => Number(item.value) === Number(state.timetableId))) {
      els.timetableSelect.value = String(state.timetableId);
    } else if (timetableOptions.length) {
      els.timetableSelect.value = String(timetableOptions[0].value);
      state.timetableId = Number(timetableOptions[0].value);
    } else {
      state.timetableId = null;
    }
  } else if (!state.timetableId && timetableOptions.length) {
    state.timetableId = Number(timetableOptions[0].value);
  }

  // Debug log
  if (els.cycleSelect) {
    console.log('renderContextSelectors: cycleSelect.innerHTML', els.cycleSelect.innerHTML);
  }
  if (els.timetableSelect) {
    console.log('renderContextSelectors: timetableSelect.innerHTML', els.timetableSelect.innerHTML);
  }

  if (els.exportBtn) {
    els.exportBtn.href = state.timetableId ? `/export.xlsx?timetable_id=${state.timetableId}` : '/export.xlsx';
  }
  if (els.deleteSelectedGroupsBtn) {
    els.deleteSelectedGroupsBtn.disabled = state.selectedGroupIds.size === 0;
  }
  if (els.exportProgramOptions) {
    els.exportProgramOptions.innerHTML = '';
    renderProgramCheckboxes(els.exportProgramOptions, state.data.programs || [], 'exportPrograms', 'code');
  }
  if (els.exportProgramBtn) {
    els.exportProgramBtn.disabled = !state.timetableId || !(state.data.programs || []).length;
  }
  if (els.exportGroupBtn) {
    els.exportGroupBtn.disabled = !state.timetableId || !(state.data.groups || []).length;
  }
  if (els.exportAllGroupBtn) {
    els.exportAllGroupBtn.disabled = !state.timetableId || !(state.data.groups || []).length;
  }
  if (els.exportCourseBtn) {
    els.exportCourseBtn.disabled = !state.timetableId || !(state.data.courses || []).length;
  }
  if (els.exportAllCourseBtn) {
    els.exportAllCourseBtn.disabled = !state.timetableId || !(state.data.courses || []).length;
  }
  if (els.exportTeacherBtn) {
    els.exportTeacherBtn.disabled = !state.timetableId || !(state.data.teachers || []).length;
  }
  if (els.exportAllTeacherBtn) {
    els.exportAllTeacherBtn.disabled = !state.timetableId || !(state.data.teachers || []).length;
  }
  if (els.editTimetableBtn) {
    els.editTimetableBtn.disabled = !state.timetableId;
  }
  if (els.deleteTimetableBtn) {
    els.deleteTimetableBtn.disabled = !state.timetableId;
  }
  if (els.addTimetableBtn) {
    els.addTimetableBtn.disabled = Boolean(selectedCycleId && timetableOptions.length);
  }
}

async function handleCycleChange() {
  const cycleId = toNullableNumber(els.cycleSelect.value);
  if (!cycleId) return;
  window.location.href = `/cycle/${cycleId}`;
}

async function handleTimetableChange() {
  state.timetableId = toNullableNumber(els.timetableSelect.value);
  await refreshData(state.timetableId);
}


function renderEntityLists() {
  renderEntityList('groupTagList', state.data.group_tags || [], 'group_tag', item => `${item.code} — ${item.name}`);
  renderEntityList('courseTagList', state.data.course_tags || [], 'course_tag', item => item.name);
  renderEntityList('programList', state.data.programs || [], 'program', item => `${item.code} — ${item.name}`);
  renderEntityList('roomList', state.data.rooms || [], 'room', item => `${item.code} — ${item.name}`, item => `Cap ${item.capacity}`);
  renderTeacherFilterByCourseTags();
  const courseTagMap = new Map((state.data.course_tags || []).map(tag => [tag.id, tag.name]));
  renderEntityList('teacherList', getFilteredTeachers(), 'teacher', item => item.name, item => {
    const tags = (item.course_tag_ids || []).map(id => courseTagMap.get(id)).filter(Boolean);
    return tags.length ? `Course tags: ${tags.join(', ')}` : 'No course tags';
  });
  const sortedCourses = (state.data.courses || []).slice().sort((a, b) => String(a.code || a.name || '').localeCompare(String(b.code || b.name || '')));
  renderEntityList('courseList', sortedCourses, 'course', item => `${item.code} — ${item.name}`, item => item.require_all ? 'Require all' : (item.elective ? 'Elective' : 'Program class'));
}

function renderColorSettings() {
  const courseTagRoot = document.getElementById('courseTagColors');
  const programRoot = document.getElementById('programColors');
  const saveBtn = document.getElementById('saveColorSettingsBtn');
  if (!courseTagRoot && !programRoot) return;

  if (courseTagRoot) {
    courseTagRoot.innerHTML = '';
    (state.data.course_tags || []).forEach(tag => {
      const row = document.createElement('div');
      row.className = 'entity-row';
      const inputId = `course-tag-color-${tag.id}`;
      row.innerHTML = `
        <div class="entity-text">
          <div>${escapeHtml(tag.name)}</div>
          <small>${escapeHtml(tag.fill_color || 'Default color')}</small>
        </div>
        <input type="color" id="${inputId}" data-entity-type="course_tag" data-entity-id="${tag.id}" value="${escapeHtml(tag.fill_color || '#ffffff')}" />
      `;
      courseTagRoot.appendChild(row);
    });
  }

  if (programRoot) {
    programRoot.innerHTML = '';
    (state.data.programs || []).forEach(program => {
      const row = document.createElement('div');
      row.className = 'entity-row';
      const inputId = `program-color-${program.id}`;
      row.innerHTML = `
        <div class="entity-text">
          <div>${escapeHtml(program.code)} — ${escapeHtml(program.name)}</div>
          <small>${escapeHtml(program.fill_color || 'Default color')}</small>
        </div>
        <input type="color" id="${inputId}" data-entity-type="program" data-entity-id="${program.id}" value="${escapeHtml(program.fill_color || '#ffffff')}" />
      `;
      programRoot.appendChild(row);
    });
  }

  if (saveBtn) {
    saveBtn.removeEventListener('click', saveColorSettings);
    saveBtn.addEventListener('click', saveColorSettings);
  }
}

const PROGRAM_FILL_VARIANTS = [
  '#FFF2CC',
  '#E8F0D9',
  '#D9E8F8',
  '#F9E2E6',
  '#EDE7F5',
  '#F7EED9',
  '#E8F2E8',
  '#F8E7F2',
  '#DFF0EB',
  '#FAE9D3',
  '#E9E8F3',
  '#F3F0E8',
  '#DDE8F0',
  '#F8ECEA',
  '#E9F1EF',
  '#F8F2DA',
  '#EDE9EC',
  '#DDE9E4',
  '#FDF3D8',
  '#E8E8F0',
];

function _stableHashCode(value) {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  return hash;
}

function normalizeCssColor(value) {
  const color = String(value || '').trim();
  if (!color) return '';
  if (color.startsWith('#')) {
    return color;
  }
  if (/^[0-9A-Fa-f]{6}$/.test(color)) {
    return `#${color}`;
  }
  return color;
}

function getProgramColor(code) {
  const normalizedCode = String(code || '').trim().toUpperCase();
  const programs = state.data?.programs || [];
  const program = programs.find(p => String(p.code || '').trim().toUpperCase() === normalizedCode);
  if (program && program.fill_color) {
    return normalizeCssColor(program.fill_color);
  }
  if (!normalizedCode) {
    return PROGRAM_FILL_VARIANTS[0];
  }
  return PROGRAM_FILL_VARIANTS[_stableHashCode(normalizedCode) % PROGRAM_FILL_VARIANTS.length];
}

function blendHexColors(colors) {
  const normalized = colors
    .map(color => normalizeCssColor(color))
    .filter(color => /^#[0-9A-F]{6}$/i.test(color))
    .map(color => color.slice(1).toUpperCase());
  if (!normalized.length) {
    return PROGRAM_FILL_VARIANTS[0];
  }
  const totals = [0, 0, 0];
  normalized.forEach(hex => {
    totals[0] += parseInt(hex.slice(0, 2), 16);
    totals[1] += parseInt(hex.slice(2, 4), 16);
    totals[2] += parseInt(hex.slice(4, 6), 16);
  });
  const count = normalized.length;
  const blended = totals.map(total => Math.round(total / count).toString(16).padStart(2, '0')).join('').toUpperCase();
  return `#${blended}`;
}

function getItemFillColor(item) {
  if (!item) return '';
  if (item.fill_color) {
    return normalizeCssColor(item.fill_color);
  }
  if (item.kind === 'program' && Array.isArray(item.program_codes) && item.program_codes.length) {
    const colors = [...new Set(item.program_codes.map(code => getProgramColor(code)).filter(Boolean))];
    if (colors.length === 1) {
      return colors[0];
    }
    return blendHexColors(colors);
  }
  return '';
}

function renderColorLegend() {
  const legendRoot = document.getElementById('timetableColorLegend');
  if (!legendRoot) return;

  const courseTags = (state.data?.course_tags || []).filter(tag => tag.fill_color);
  const programs = state.data?.programs || [];

  const entries = [];
  if (courseTags.length) {
    entries.push('<div class="legend-color-group"><div class="legend-group-title">Course tag colors</div>');
    courseTags.forEach(tag => {
      const swatch = normalizeCssColor(tag.fill_color);
      entries.push(`
        <div class="legend-color-entry">
          <span class="legend-color-swatch" style="background:${escapeHtml(swatch)}"></span>
          <span>${escapeHtml(tag.name)}</span>
        </div>
      `);
    });
    entries.push('</div>');
  }
  if (programs.length) {
    entries.push('<div class="legend-color-group"><div class="legend-group-title">Study program colors</div>');
    programs.forEach(prog => {
      const displayColor = getProgramColor(prog.code);
      entries.push(`
        <div class="legend-color-entry">
          <span class="legend-color-swatch" style="background:${escapeHtml(displayColor)}"></span>
          <span>${escapeHtml(prog.code)}</span>
        </div>
      `);
    });
    entries.push('</div>');
  }
  legendRoot.innerHTML = entries.join('');
}

function setSaveColorStatus(message, type = 'info') {
  const status = document.getElementById('saveColorStatus');
  if (!status) return;
  status.textContent = message;
  status.className = `save-color-status ${type}`;
}

async function saveColorSettings() {
  const status = document.getElementById('saveColorStatus');
  if (status) {
    status.textContent = '';
    status.className = 'save-color-status';
  }
  const updates = [];
  document.querySelectorAll('input[data-entity-type][data-entity-id]').forEach(input => {
    const entityType = input.dataset.entityType;
    const entityId = Number(input.dataset.entityId);
    const value = input.value || null;
    if (!entityType || !entityId) return;
    const existing = (entityType === 'course_tag' ? state.data.course_tags : state.data.programs || []).find(item => item.id === entityId);
    if (!existing) return;
    if (existing.fill_color !== value) {
      updates.push({ entityType, entityId, value, existing });
    }
  });
  if (!updates.length) {
    setSaveColorStatus('No color changes detected.', 'info');
    return;
  }
  const errors = [];
  for (const update of updates) {
    const payload = { fill_color: update.value };
    if (update.entityType === 'course_tag') {
      payload.name = update.existing.name;
    } else {
      payload.code = update.existing.code;
      payload.name = update.existing.name;
    }
    const res = await fetch(`${CRUD[update.entityType]}/${update.entityId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      errors.push(`${update.entityType} ${update.entityId}: ${data.detail || res.statusText}`);
    }
  }
  if (errors.length) {
    setSaveColorStatus('Some colors could not be saved.', 'error');
  } else {
    setSaveColorStatus('Color settings saved successfully.', 'success');
  }
  await refreshData(state.timetableId, state.selectedCycleId);
}

function getFilteredTeachers() {
  const teachers = state.data?.teachers || [];
  const selectedTagIds = Array.from(state.selectedTeacherCourseTagIds);
  if (!selectedTagIds.length) return teachers;
  return teachers.filter(teacher => {
    const teacherTags = teacher.course_tag_ids || [];
    return selectedTagIds.some(tagId => teacherTags.includes(tagId));
  });
}

function renderTeacherFilterByCourseTags() {
  if (!els.teacherCourseTagFilter) return;
  const courseTags = (state.data?.course_tags || []).slice().sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
  els.teacherCourseTagFilter.innerHTML = '';
  if (!courseTags.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No course tags available';
    els.teacherCourseTagFilter.appendChild(opt);
    els.teacherCourseTagFilter.disabled = true;
    return;
  }

  const defaultOption = document.createElement('option');
  defaultOption.value = '';
  defaultOption.textContent = 'All tags';
  els.teacherCourseTagFilter.appendChild(defaultOption);

  courseTags.forEach(tag => {
    const opt = document.createElement('option');
    opt.value = String(tag.id);
    opt.textContent = tag.name;
    if (state.selectedTeacherCourseTagIds.has(tag.id)) {
      opt.selected = true;
    }
    els.teacherCourseTagFilter.appendChild(opt);
  });

  els.teacherCourseTagFilter.addEventListener('change', () => {
    const value = els.teacherCourseTagFilter.value;
    state.selectedTeacherCourseTagIds.clear();
    if (value) {
      state.selectedTeacherCourseTagIds.add(Number(value));
    }
    updateTeacherFilterQueryString();
    renderEntityLists();
  });
}

function updateTeacherFilterQueryString() {
  const query = new URLSearchParams(window.location.search);
  query.delete('course_tag_id');
  query.delete('course_tag_ids');
  state.selectedTeacherCourseTagIds.forEach(id => query.append('course_tag_ids', id));
  const newUrl = `${window.location.pathname}${query.toString() ? `?${query.toString()}` : ''}`;
  window.history.replaceState({}, '', newUrl);
}

function initTeacherFilterFromQuery() {
  if (!window.location.pathname.startsWith('/teachers')) return;
  const query = new URLSearchParams(window.location.search);
  query.getAll('course_tag_ids').forEach(value => {
    const id = Number(value);
    if (id) state.selectedTeacherCourseTagIds.add(id);
  });
  const singleTagId = Number(query.get('course_tag_id'));
  if (singleTagId) {
    state.selectedTeacherCourseTagIds.add(singleTagId);
  }
}

function renderEntityList(containerId, items, type, labelFn, metaFn = null) {
  const root = els[containerId];
  if (!root) return;
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
  if (els.groupTagSelect) {
    fillSelect(
      els.groupTagSelect,
      (state.data.group_tags || []).map(item => ({ value: item.id, label: `${item.code} — ${item.name}` })),
      true
    );
  }

  if (els.entityCycleSelect) {
    fillSelect(
      els.entityCycleSelect,
      (state.data.cycles || []).map(item => ({ value: item.id, label: `${item.name} (${item.year_starting})` })),
      true
    );
  }

  if (els.entityCourseTagSelect) {
    fillSelect(
      els.entityCourseTagSelect,
      (state.data.course_tags || []).map(item => ({ value: item.id, label: item.name })),
      true
    );
  }

  if (els.groupProgramOptions) {
    renderProgramCheckboxes(els.groupProgramOptions, state.data.programs || [], 'groupPrograms');
  }
  if (els.entityCoursePrograms) {
    renderProgramCheckboxes(els.entityCoursePrograms, state.data.programs || [], 'entityPrograms');
  }
  if (els.entityTeacherTags) {
    renderProgramCheckboxes(els.entityTeacherTags, state.data.course_tags || [], 'entityTeacherTags', 'name');
  }
  if (els.roomSelect) {
    fillSelect(
      els.roomSelect,
      [{ value: '', label: 'No room' }, ...(state.data.rooms || []).map(r => ({ value: r.id, label: `${r.code} (${r.capacity})` }))],
      false
    );
  }
  syncClassFormVisibility();
}

function renderTeacherLoad() {
  if (!els.teacherLoadList) return;
  els.teacherLoadList.innerHTML = '';
  (state.data.teacher_load || []).forEach(item => {
    const div = document.createElement('div');
    div.className = 'teacher-load-row';
    const teacherName = escapeHtml(item.teacher);
    const rowCount = Number(item.timeslot_count) || 0;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost-btn small';
    button.textContent = 'View schedule';
    button.addEventListener('click', event => {
      event.stopPropagation();
      openTeacherScheduleModal(item);
    });
    div.innerHTML = `<span>${teacherName}</span><strong>${rowCount}</strong>`;
    div.appendChild(button);
    els.teacherLoadList.appendChild(div);
  });
}

function openTeacherScheduleModal(item) {
  if (!els.teacherScheduleModal || !els.teacherScheduleModalTitle || !els.teacherScheduleTableWrapper) return;
  const teacherName = item.teacher;
  const teacherId = item.teacher_id ?? null;
  els.teacherScheduleModalTitle.textContent = `Teacher schedule: ${teacherName}`;
  renderTeacherScheduleTable(teacherId, teacherName);
  openModal('teacherScheduleModal');
}

function openGroupScheduleModal(item) {
  if (!els.groupScheduleModal || !els.groupScheduleModalTitle || !els.groupScheduleTableWrapper) return;
  const groupCode = item.group_code || item.groupCode || 'Group';
  const groupId = item.group_id ?? null;
  els.groupScheduleModalTitle.textContent = `Group schedule: ${groupCode}`;
  renderGroupScheduleTable(groupId, groupCode);
  openModal('groupScheduleModal');
}

function renderTeacherScheduleTable(teacherId, teacherName) {
  if (!els.teacherScheduleTableWrapper) return;
  els.teacherScheduleTableWrapper.innerHTML = '';
  const rows = buildTeacherScheduleRows(teacherId, teacherName);
  if (!rows.length) {
    const msg = document.createElement('div');
    msg.className = 'muted';
    msg.textContent = 'No scheduled classes found for this teacher.';
    els.teacherScheduleTableWrapper.appendChild(msg);
    return;
  }

  const table = document.createElement('table');
  table.className = 'requirements-modal-table';
  const thead = document.createElement('thead');
  thead.innerHTML = `
    <tr>
      <th>Day</th>
      <th>Timeslot</th>
      <th>Group</th>
      <th>Program</th>
      <th>Room</th>
      <th>Course</th>
    </tr>
  `;
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(row.weekday)}</td>
      <td>${escapeHtml(row.timeslot)}</td>
      <td>${escapeHtml(row.group_code)}</td>
      <td>${escapeHtml(row.program_code)}</td>
      <td>${escapeHtml(row.room_name)}</td>
      <td>${escapeHtml(row.course_name)}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  els.teacherScheduleTableWrapper.appendChild(table);
}

function renderGroupScheduleTable(groupId, groupCode) {
  if (!els.groupScheduleTableWrapper) return;
  els.groupScheduleTableWrapper.innerHTML = '';
  const rows = buildGroupScheduleRows(groupId, groupCode);
  if (!rows.length) {
    const msg = document.createElement('div');
    msg.className = 'muted';
    msg.textContent = 'No scheduled classes found for this group.';
    els.groupScheduleTableWrapper.appendChild(msg);
    return;
  }

  const table = document.createElement('table');
  table.className = 'requirements-modal-table';
  const thead = document.createElement('thead');
  thead.innerHTML = `
    <tr>
      <th>Day</th>
      <th>Timeslot</th>
      <th>Teacher</th>
      <th>Program</th>
      <th>Room</th>
      <th>Course</th>
    </tr>
  `;
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(row.weekday)}</td>
      <td>${escapeHtml(row.timeslot)}</td>
      <td>${escapeHtml(row.teacher_name)}</td>
      <td>${escapeHtml(row.program_code)}</td>
      <td>${escapeHtml(row.room_name)}</td>
      <td>${escapeHtml(row.course_name)}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  els.groupScheduleTableWrapper.appendChild(table);
}

function buildGroupScheduleRows(groupId, groupCode) {
  const timeslotMap = new Map((state.data.timeslots || []).map(ts => [String(ts.id), ts]));
  const cells = state.data.cells || {};
  const grouped = new Map();

  Object.entries(cells).forEach(([timeslotId, groups]) => {
    const timeslot = timeslotMap.get(timeslotId);
    if (!timeslot || typeof groups !== 'object' || groups === null) return;
    Object.entries(groups).forEach(([cellGroupId, items]) => {
      if (!Array.isArray(items) || String(cellGroupId) !== String(groupId)) return;
      items.forEach(item => {
        const rowKey = [
          String(timeslot.weekday || ''),
          Number(timeslot.sort_order) || 0,
          String(timeslot.label || ''),
          String(item.teacher_name || ''),
          String(item.room_name || ''),
          String(item.kind || ''),
          String(item.course_name || ''),
        ].join('||');

        const courseLabel = item.course_name || '';
        const existing = grouped.get(rowKey) || {
          weekday: timeslot.weekday || '',
          sort_order: Number(timeslot.sort_order) || 0,
          timeslot: timeslot.label || '',
          teacher_name: item.teacher_name || '',
          room_name: item.room_name || '',
          course_name: item.kind === 'elective' ? `(Elective) ${courseLabel}` : courseLabel,
          program_codes: new Set(),
        };

        if (Array.isArray(item.program_codes)) {
          item.program_codes.forEach(code => {
            if (code) existing.program_codes.add(code);
          });
        }
        grouped.set(rowKey, existing);
      });
    });
  });

  const rows = Array.from(grouped.values()).map(entry => ({
    weekday: entry.weekday,
    sort_order: entry.sort_order,
    timeslot: entry.timeslot,
    teacher_name: entry.teacher_name,
    program_code: Array.from(entry.program_codes).sort().join(', '),
    room_name: entry.room_name,
    course_name: entry.course_name,
  }));

  rows.sort((a, b) => a.sort_order - b.sort_order || a.weekday.localeCompare(b.weekday) || a.timeslot.localeCompare(b.timeslot));
  return rows;
}

function buildTeacherScheduleRows(teacherId, teacherName) {
  const timeslotMap = new Map((state.data.timeslots || []).map(ts => [String(ts.id), ts]));
  const groupMap = new Map((state.data.groups || []).map(g => [String(g.id), g]));
  const cells = state.data.cells || {};
  const grouped = new Map();

  Object.entries(cells).forEach(([timeslotId, groups]) => {
    const timeslot = timeslotMap.get(timeslotId);
    if (!timeslot || typeof groups !== 'object' || groups === null) return;
    Object.entries(groups).forEach(([groupId, items]) => {
      if (!Array.isArray(items)) return;
      items.forEach(item => {
        const matchesTeacher = teacherId != null ? item.teacher_id === teacherId : item.teacher_name === teacherName;
        if (!matchesTeacher) return;
        const rowKey = [
          String(timeslot.weekday || ''),
          Number(timeslot.sort_order) || 0,
          String(timeslot.label || ''),
          String(item.room_name || ''),
          String(item.course_name || ''),
        ].join('||');

        const existing = grouped.get(rowKey) || {
          weekday: timeslot.weekday || '',
          sort_order: Number(timeslot.sort_order) || 0,
          timeslot: timeslot.label || '',
          group_codes: new Set(),
          program_codes: new Set(),
          room_name: item.room_name || '',
          course_name: item.course_name || '',
        };

        const groupCode = groupMap.get(groupId)?.code || '';
        if (groupCode) {
          existing.group_codes.add(groupCode);
        }
        if (Array.isArray(item.program_codes)) {
          item.program_codes.forEach(code => {
            if (code) existing.program_codes.add(code);
          });
        }
        grouped.set(rowKey, existing);
      });
    });
  });

  const rows = Array.from(grouped.values()).map(entry => ({
    weekday: entry.weekday,
    sort_order: entry.sort_order,
    timeslot: entry.timeslot,
    group_code: Array.from(entry.group_codes).sort().join(', '),
    program_code: Array.from(entry.program_codes).sort().join(', '),
    room_name: entry.room_name,
    course_name: entry.course_name,
  }));

  rows.sort((a, b) => a.sort_order - b.sort_order || a.weekday.localeCompare(b.weekday) || a.timeslot.localeCompare(b.timeslot));
  return rows;
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
  if (!els.timetableBoard) return;

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
    const checked = state.selectedGroupIds.has(group.id) ? 'checked' : '';
    th.innerHTML = `
      <div class="group-header-top" style="display:flex;flex-direction:column;gap:8px;">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
          <label class="group-select-label" style="display:flex;align-items:center;">
            <input type="checkbox" class="group-select-checkbox" data-group-id="${group.id}" ${checked} />
          </label>
          <button type="button" class="ghost-btn small" data-view-group-schedule="${group.id}" title="View schedule">View schedule</button>
        </div>
        <div class="group-title-wrap">
          <div class="group-code">${escapeHtml(group.code)}</div>
          <small>${escapeHtml(group.programs.map(p => p.code).join('/'))}</small>
        </div>
        <div class="group-menu-wrap">
          <button class="dots-btn" data-group-menu="${group.id}" title="Group options">...</button>
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
    const scheduleBtn = th.querySelector('[data-view-group-schedule]');
    if (scheduleBtn) {
      scheduleBtn.addEventListener('click', event => {
        event.stopPropagation();
        openGroupScheduleModal({ group_id: group.id, group_code: group.code });
      });
    }
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
    const checkbox = th.querySelector('.group-select-checkbox');
    if (checkbox) {
      checkbox.addEventListener('click', event => event.stopPropagation());
      checkbox.addEventListener('change', () => toggleGroupSelection(group.id, checkbox.checked));
    }
    hrow.appendChild(th);
  });
  const addTh = document.createElement('th');
  addTh.className = 'add-group-col';
  addTh.innerHTML = `<button class="plus-btn" id="openGroupModalBtn" title="Add group">ï¼‹</button>`;
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
    const isGermanSlot = String(slot.label || '').startsWith('German');
    groups.forEach(group => {
      const items = (cells[String(slot.id)] || {})[String(group.id)] || [];
      const map = {};
      items.forEach(item => {
        if (isGermanSlot && item.kind === 'elective') return;
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
      if (index === 0 && day !== 'MONDAY') {
        const divider = document.createElement('tr');
        divider.className = 'day-divider-row';
        const dividerCell = document.createElement('td');
        dividerCell.colSpan = groups.length + 2;
        divider.appendChild(dividerCell);
        tbody.appendChild(divider);
      }

      const tr = document.createElement('tr');
      if (index === 0) {
        const dayCell = document.createElement('td');
        dayCell.className = 'day-cell';
        dayCell.rowSpan = daySlots.length + 1;
        dayCell.textContent = day.replace('DAY', '');
        tr.appendChild(dayCell);
      }

      const timeTd = document.createElement('td');
      timeTd.className = 'slot-label time-cell';
      timeTd.textContent = slot.label.startsWith('German')
        ? slot.label.replace(/^German/, 'GER')
        : slot.label;
      tr.appendChild(timeTd);

        const isGermanSlot = slot.label.startsWith('German');
      const rowKeys = slotRowMap[String(slot.id)]?.keys || [];
      const rows = Math.max(1, rowKeys.length);

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
        const totalPadding = 12; // 6px top + 6px bottom
        const totalGaps = 6 * Math.max(0, rows - 1);
        stack.style.height = `${rows * 160 + totalPadding + totalGaps}px`;
        stack.style.minHeight = stack.style.height;
        const itemsByKey = slotRowMap[String(slot.id)]?.groupItemsByKey[String(group.id)] || {};
        for (let i = 0; i < rows; i += 1) {
          const strip = document.createElement('div');
          const item = itemsByKey[rowKeys[i]];
          if (item) {
            strip.className = `strip filled ${item.color_key} ${item.kind}`;
              const fillColor = getItemFillColor(item);
            if (fillColor) {
              strip.style.backgroundImage = '';
              strip.style.backgroundColor = fillColor;
              strip.style.borderColor = fillColor;
            } else {
              const isProgram = item.kind === 'program' && Array.isArray(item.program_codes) && item.program_codes.length > 1;
              if (isProgram) {
                const colors = [...new Set(item.program_codes.map(code => getProgramColor(code)).filter(Boolean))];
                if (colors.length > 1) {
                  const stops = colors.map((color, index) => {
                    const start = (index * 100) / colors.length;
                    const end = ((index + 1) * 100) / colors.length;
                    return `${color} ${start}% ${end}%`;
                  }).join(', ');
                  strip.style.backgroundImage = `linear-gradient(90deg, ${stops})`;
                  strip.style.backgroundColor = colors[0];
                  strip.style.borderColor = colors[0];
                } else if (colors.length === 1) {
                  strip.style.backgroundColor = colors[0];
                  strip.style.borderColor = colors[0];
                }
              }
            }
            strip.innerHTML = renderStrip(item);
          } else {
            strip.className = 'strip empty';
          }
          if (!isGermanSlot && rowKeys.length === 0 && i === rows - 1 && !item) {
            strip.classList.add('plus');
            strip.innerHTML = '<span class="plus-icon">+</span>';
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
              await refreshData(state.timetableId, state.selectedCycleId);
            }
          } else if (e.target.matches('[data-edit-class]')) {
            e.stopPropagation();
            const classId = e.target.getAttribute('data-edit-class');
            const mergedClassIds = e.target.getAttribute('data-merged-class-ids');
            openClassModal(classId, mergedClassIds ? mergedClassIds.split(',').map(id => Number(id)) : null);
          }
        });
      });

      const filler = document.createElement('td');
      filler.className = 'add-group-col cell-filler';
      tr.appendChild(filler);
      tbody.appendChild(tr);

      if (slot.end === '12.00') {
        const lunch = document.createElement('tr');
        lunch.className = 'lunch-row';
        lunch.innerHTML = `<td class="slot-label lunch">Lunch break</td><td colspan="${groups.length + 1}"></td>`;
        tbody.appendChild(lunch);
      }
    });
  });

  els.timetableBoard.appendChild(tbody);
  renderGroupProgramPanel();
  renderColorLegend();
}

function toggleGroupSelection(groupId, checked) {
  if (checked) {
    state.selectedGroupIds.add(groupId);
  } else {
    state.selectedGroupIds.delete(groupId);
  }
  if (els.deleteSelectedGroupsBtn) {
    els.deleteSelectedGroupsBtn.disabled = state.selectedGroupIds.size === 0;
  }
}

async function deleteSelectedGroups() {
  const ids = Array.from(state.selectedGroupIds);
  if (!ids.length) return;
  if (!confirm(`Delete ${ids.length} selected group${ids.length === 1 ? '' : 's'}? This will also remove all classes for those groups.`)) return;
  for (const groupId of ids) {
    const res = await fetch(`/api/groups/${groupId}`, { method: 'DELETE' });
    const data = await safeJson(res);
    if (!res.ok) {
      alert(formatError(data));
      return;
    }
  }
  state.selectedGroupIds.clear();
  if (els.deleteSelectedGroupsBtn) {
    els.deleteSelectedGroupsBtn.disabled = true;
  }
  await refreshData(state.timetableId, state.selectedCycleId);
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
    timetable_id: group.timetable_id || state.timetableId,
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
  const titleText = String(item.course_code || item.course_name || 'Untitled course').trim();
  const courseHtml = `
    <div class="strip-title">${escapeHtml(titleText)}</div>
  `;
  const programHtml = item.program_codes && item.program_codes.length
    ? `<div class="strip-programs">${escapeHtml(item.program_codes.join(', '))}</div>`
    : '';
  const groupHtml = item.group_codes?.length ? `<div class="strip-groups">${escapeHtml(item.group_codes.join(', '))}</div>` : '';
  const teacherHtml = item.teacher_name ? `<span class="strip-meta">${escapeHtml(item.teacher_name)}</span>` : '';
  const roomHtml = item.room_name ? `<span class="strip-meta">${escapeHtml(item.room_name)}</span>` : '';
  const indicators = [];
  if (item.kind === 'elective') indicators.push('E');
  if (item.kind === 'program' && item.class_ids?.length > 1) indicators.push('Ps');
  if (item.shared) indicators.push('Gs');
  const indicatorHtml = indicators.length > 0
    ? `<div class="strip-indicators">${indicators.map(code => `<span class="strip-indicator">${escapeHtml(code)}</span>`).join('')}</div>`
    : '';
  const buttonHtml = item.class_ids?.length
    ? `<div class="strip-footer"><button type="button" class="danger-btn small inline-delete" data-delete-class="${item.class_ids[0]}" data-merged-count="${item.class_ids.length}">Delete</button><button type="button" class="ghost-btn small inline-edit" data-edit-class="${item.class_ids[0]}" data-merged-count="${item.class_ids.length}"${item.class_ids.length > 1 ? ` data-merged-class-ids="${item.class_ids.join(',')}"` : ''}>Edit</button></div>`
    : '';

  const headerHtml = `
    <div class="strip-header">
      ${courseHtml}
      ${programHtml}
      ${indicatorHtml}
    </div>
  `;

  return `
    ${headerHtml}
    <div class="strip-top">
      <div class="strip-main">${groupHtml}</div>
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
    return;
  }
  const codes = state.selected.map(item => item.groupCode).join(', ');
  els.selectionText.textContent = `${state.selected[0].slotLabel} → ${codes}`;
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
      if (els.entityForm.elements.german_timeslots) {
        els.entityForm.elements.german_timeslots.checked = !!item.german_timeslots;
      }
    } else if (type === 'timetable') {
      els.entityCycleSelect.value = String(item.cycle_id);
    } else if (type === 'group_tag') {
      els.entityForm.elements.code.value = item.code;
      els.entityForm.elements.name.value = item.name;
      (item.requirements || []).forEach(req => addEntityRequirementRow(req.course_id, req.sessions_required));
    } else if (type === 'course_tag') {
      els.entityForm.elements.name.value = item.name;
      if (els.entityFillColorInput) els.entityFillColorInput.value = item.fill_color || '#ffffff';
    } else if (type === 'program') {
      els.entityForm.elements.code.value = item.code;
      els.entityForm.elements.name.value = item.name;
      if (els.entityFillColorInput) els.entityFillColorInput.value = item.fill_color || '#ffffff';
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
      if (cycleId) {
        const existing = (state.data.timetables || []).some(item => item.cycle_id === cycleId);
        if (existing) {
          alert('A timetable already exists for this cycle. Only one timetable per cycle is supported.');
          return;
        }
        els.entityCycleSelect.value = String(cycleId);
      }
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
  const show = (id, visible) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('hidden', !visible);
  };
  show('entityNameWrap', ['cycle', 'group_tag', 'course_tag', 'program', 'room', 'teacher', 'course'].includes(type));
  show('entityCodeWrap', ['group_tag', 'program', 'room', 'course'].includes(type));
  show('entityYearWrap', type === 'cycle');
  show('entityGermanTimeslotWrap', type === 'cycle');
  show('entityCapacityWrap', type === 'room');
  show('entityCycleWrap', type === 'timetable');
  show('entityCourseTagWrap', type === 'course');
  show('entityFillColorWrap', type === 'course_tag' || type === 'program');
  show('entityInActionWrap', false);
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
  const reloadEntityTypes = new Set(['room', 'course', 'teacher', 'course_tag', 'group_tag', 'group']);
  if (reloadEntityTypes.has(type)) {
    window.location.reload();
    return;
  }

  const query = new URLSearchParams(window.location.search);
  const cycleId = state.selectedCycleId || Number(query.get('cycle_id')) || null;
  await refreshData(state.timetableId, cycleId);
}

function buildEntityPayload(type) {
  const f = els.entityForm.elements;
  if (type === 'cycle') {
    return {
      name: f.name.value,
      year_starting: Number(f.year_starting.value),
      german_timeslots: !!f.german_timeslots?.checked,
    };
  }
  if (type === 'timetable') {
    return {
      cycle_id: Number(els.entityCycleSelect.value),
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
    return { name: f.name.value, fill_color: f.fill_color?.value || null };
  }
  if (type === 'program') {
    return { code: f.code.value, name: f.name.value, fill_color: f.fill_color?.value || null };
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
  const reloadEntityTypes = new Set(['room', 'course', 'teacher', 'course_tag', 'group_tag', 'group']);
  if (reloadEntityTypes.has(type)) {
    window.location.reload();
    return;
  }
  const query = new URLSearchParams(window.location.search);
  const cycleId = state.selectedCycleId || Number(query.get('cycle_id')) || null;
  await refreshData(state.timetableId, cycleId);
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
  window.location.reload();
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
  state.editingGroupId = null;
  closeModal('groupModal');
  window.location.reload();
}

async function openClassModal(classId = null, mergedClassIds = null) {
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
      const timeslot = (state.data.timeslots || []).find(ts => ts.id === editingClass.timeslot_id);
      const slotLabel = timeslot
        ? `${timeslot.weekday || ''} ${editingClass.timeslot_label || ''}`
        : (editingClass.timeslot_label || '');
      if (mergedClassIds?.length > 1) {
        const selections = [];
        for (const mergedId of mergedClassIds) {
          const mergedRes = await fetch(`/api/classes/${mergedId}`);
          if (!mergedRes.ok) continue;
          const mergedClass = await mergedRes.json();
          selections.push({
            groupId: mergedClass.group_id,
            groupCode: mergedClass.group_code || '',
            timeslotId: mergedClass.timeslot_id,
            slotLabel,
          });
        }
        if (selections.length) {
          selected = selections;
        } else {
          selected = [{
            groupId: editingClass.group_id,
            groupCode: editingClass.group_code || '',
            timeslotId: editingClass.timeslot_id,
            slotLabel,
          }];
        }
      } else {
        selected = [{
          groupId: editingClass.group_id,
          groupCode: editingClass.group_code || '',
          timeslotId: editingClass.timeslot_id,
          slotLabel,
        }];
      }
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
    const defaultRadio = els.classForm.querySelector('input[name="mode"][value="required_all"]');
    if (defaultRadio) defaultRadio.checked = true;
    if (els.classProgramOptions) {
      els.classProgramOptions.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
    }
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
  const selectedTimeslotId = selected[0].timeslotId;
  syncClassFormVisibility(editingClass ? editingClass.course_id : null);
  updateRoomOptions(editingClass ? editingClass.room_id : null, selectedTimeslotId, editingClass ? editingClass.course_id : null);

  // Pre-fill form if editing
  if (editingClass) {
    els.courseSelect.value = editingClass.course_id || '';
    updateTeacherOptions(editingClass.teacher_id, selectedTimeslotId, editingClass.course_id);
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

function syncClassFormVisibility(currentCourseId = null) {
  if (!els.classForm) return;
  const mode = els.classForm.querySelector('input[name="mode"]:checked')?.value;
  if (!mode) return;
  const effectiveMode = mode;
  let courses = state.data.courses || [];
  let filteredByProgram = false;

  const selectedProgramIds = collectCheckedValues(els.classProgramOptions);
  if (mode === 'program') {
    if (selectedProgramIds.length > 0) {
      filteredByProgram = true;
      const selectedPrograms = (state.data.programs || []).filter(p => selectedProgramIds.includes(p.id));
      const programCourseIds = new Set();
      const programRequiredCourseIds = new Set();
      selectedPrograms.forEach(program => {
        if (program.requirements) {
          program.requirements.forEach(req => {
            if (req.course_id) {
              programCourseIds.add(req.course_id);
            }
          });
        }
      });

      const selectedGroupIds = getClassGroupIds().length ? getClassGroupIds() : (state.selected || []).map(item => item.groupId);
      if (selectedGroupIds.length > 0) {
        selectedGroupIds.forEach(groupId => {
          const group = (state.data.groups || []).find(g => g.id === groupId);
          if (!group) return;
          const groupProgramIds = group.programs.map(p => p.id);
          const deployedCounts = getDeployedCourseCountsForGroup(groupId);
          selectedProgramIds.forEach(programId => {
            if (!groupProgramIds.includes(programId)) return;
            const program = selectedPrograms.find(p => p.id === programId);
            if (!program || !program.requirements) return;
            program.requirements.forEach(req => {
              const courseId = req.course_id;
              if (!courseId) return;
              const sessionsRequired = req.sessions_required || 1;
              const deployed = deployedCounts[courseId] || 0;
              if (deployed < sessionsRequired) {
                programRequiredCourseIds.add(courseId);
              }
            });
          });
        });
      }

      if (selectedGroupIds.length > 0) {
        if (programRequiredCourseIds.size > 0) {
          courses = courses.filter(c => programRequiredCourseIds.has(c.id));
        } else if (programCourseIds.size > 0) {
          if (currentCourseId != null && programCourseIds.has(currentCourseId)) {
            courses = courses.filter(c => c.id === currentCourseId);
          } else {
            courses = [];
          }
        } else {
          courses = [];
        }
      } else if (programCourseIds.size > 0) {
        courses = courses.filter(c => programCourseIds.has(c.id));
      } else {
        courses = (state.data.courses || []).filter(c => c.study_program_ids && c.study_program_ids.some(pid => selectedProgramIds.includes(pid)));
      }
    }
  }

  let requiredCourseIds = null;
  const selectedGroupIds = getClassGroupIds().length ? getClassGroupIds() : (state.selected || []).map(item => item.groupId);
  if (!filteredByProgram && selectedGroupIds.length > 0 && mode !== 'elective') {
    // Only show courses still required by the selected group(s) for non-elective modes.
    requiredCourseIds = new Set();
    selectedGroupIds.forEach(groupId => {
      const group = (state.data.groups || []).find(g => g.id === groupId);
      if (!group) return;
      const deployedCounts = getDeployedCourseCountsForGroup(groupId);
      const allReqs = [...(group.requirements || []), ...(group.group_requirements || [])];
      allReqs.forEach(req => {
        const courseId = req.course_id;
        if (!courseId) return;
        const sessionsRequired = req.sessions_required || 1;
        const deployed = deployedCounts[courseId] || 0;
        if (deployed < sessionsRequired) {
          requiredCourseIds.add(courseId);
        }
      });
    });
    if (requiredCourseIds.size > 0) {
      courses = courses.filter(c => requiredCourseIds.has(c.id));
    }
  }

  if (currentCourseId != null && !courses.some(c => c.id === currentCourseId)) {
    const existingCourse = (state.data.courses || []).find(c => c.id === currentCourseId);
    if (existingCourse) {
      courses = [existingCourse, ...courses];
    }
  }

  // Filter by mode as before, but preserve required course selection for required_all mode.
  courses = courses.filter(course => {
    if (mode === 'required_all') {
      const isRequired = course.require_all;
      if (requiredCourseIds && requiredCourseIds.size > 0) {
        return isRequired && requiredCourseIds.has(course.id);
      }
      return false;
    }
    if (mode === 'program') {
      return !course.require_all && !course.elective;
    }
    return course.elective;
  });

  if (currentCourseId != null && !courses.some(c => c.id === currentCourseId)) {
    const existingCourse = (state.data.courses || []).find(c => c.id === currentCourseId);
    if (existingCourse) {
      courses = [existingCourse, ...courses];
    }
  }

  const allowProgramMode = selectedProgramIds.length > 0;
  const courseOptions = courses
    .slice()
    .sort((a, b) => String(a.code || a.name || '').localeCompare(String(b.code || b.name || '')))
    .map(c => ({ value: c.id, label: c.code ? `${c.code} — ${c.name}` : c.name }));
  fillSelect(els.courseSelect, courseOptions, true);

  const showProgramSelection = effectiveMode !== 'required_all';
  els.programSelectionBox.classList.toggle('hidden', !showProgramSelection);
  els.programClassHint.classList.toggle('hidden', !(effectiveMode === 'program' && !allowProgramMode));
  els.courseSelect.disabled = effectiveMode === 'program' && !allowProgramMode;
  const showGroupSelection = effectiveMode !== 'required_all';
  els.groupSelectionBox.classList.toggle('hidden', !showGroupSelection);
  if (els.roomSelect) {
    els.roomSelect.disabled = false;
  }
  updateClassGroupOptions();
  els.classForm.querySelectorAll('input[name="mode"]').forEach(radio => {
    if (radio.value === 'program') {
      radio.disabled = false;
    }
  });
  const courseId = Number(els.courseSelect.value) || null;
  updateTeacherOptions(null, null, courseId);
  updateRoomOptions(null, null, courseId);
  els.courseSelect.onchange = () => {
    const selectedCourseId = Number(els.courseSelect.value) || null;
    updateTeacherOptions(null, null, selectedCourseId);
    updateRoomOptions(null, null, selectedCourseId);
  };
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

function getTimeslotOccupancy(timeslotId) {
  const occupiedTeacherIds = new Set();
  const occupiedRoomIds = new Set();
  const teacherConflictGroupsById = {};
  const roomConflictGroupsById = {};
  const cells = state.data.cells || {};
  const slotMap = cells[String(timeslotId)] || {};
  const groupMap = new Map((state.data.groups || []).map(g => [String(g.id), g.code || '']));
  Object.entries(slotMap).forEach(([groupId, items]) => {
    if (!Array.isArray(items)) return;
    const groupCode = groupMap.get(groupId) || '';
    items.forEach(item => {
      const courseLabel = item.course_name || item.course_code || 'Unknown class';
      const roomKey = item.room_id != null ? String(item.room_id) : '';
      const teacherId = item.teacher_id;
      if (teacherId) {
        occupiedTeacherIds.add(teacherId);
        teacherConflictGroupsById[teacherId] = teacherConflictGroupsById[teacherId] || new Map();
        const teacherKey = `${roomKey}||${courseLabel}`;
        const teacherEntry = teacherConflictGroupsById[teacherId].get(teacherKey) || { groupCodes: new Set(), courseLabel };
        if (groupCode) teacherEntry.groupCodes.add(groupCode);
        teacherConflictGroupsById[teacherId].set(teacherKey, teacherEntry);
      }
      if (item.room_id) {
        occupiedRoomIds.add(item.room_id);
        roomConflictGroupsById[item.room_id] = roomConflictGroupsById[item.room_id] || new Map();
        const roomKey = `${courseLabel}`;
        const roomEntry = roomConflictGroupsById[item.room_id].get(roomKey) || { groupCodes: new Set(), courseLabel };
        if (groupCode) roomEntry.groupCodes.add(groupCode);
        roomConflictGroupsById[item.room_id].set(roomKey, roomEntry);
      }
    });
  });

  const teacherConflictsById = Object.fromEntries(Object.entries(teacherConflictGroupsById).map(([id, map]) => {
    const labels = Array.from(map.values()).map(entry => {
      const groups = entry.groupCodes.size ? Array.from(entry.groupCodes).sort().join('/') : '';
      return groups ? `${groups} — ${entry.courseLabel}` : entry.courseLabel;
    });
    return [id, labels];
  }));

  const roomConflictsById = Object.fromEntries(Object.entries(roomConflictGroupsById).map(([id, map]) => {
    const labels = Array.from(map.values()).map(entry => {
      const groups = entry.groupCodes.size ? Array.from(entry.groupCodes).sort().join('/') : '';
      return groups ? `${groups} — ${entry.courseLabel}` : entry.courseLabel;
    });
    return [id, labels];
  }));

  return {
    occupiedTeacherIds,
    occupiedRoomIds,
    teacherConflictsById,
    roomConflictsById,
  };
}

function updateRoomOptions(currentRoomId = null, timeslotId = null, courseId = null) {
  if (!els.roomSelect) return;
  if (timeslotId == null && state.selected && state.selected.length) {
    timeslotId = state.selected[0].timeslotId;
  }
  const { occupiedRoomIds, roomConflictsById } = getTimeslotOccupancy(timeslotId);
  fillSelect(
    els.roomSelect,
    [
      { value: '', label: 'No room' },
      ...(state.data.rooms || []).map(r => {
        const conflicts = roomConflictsById[r.id] || [];
        const occupied = occupiedRoomIds.has(r.id) && r.id !== currentRoomId;
        return {
          value: r.id,
          label: `${r.code} (${r.capacity})${conflicts.length ? ` — occupied by ${conflicts.join(', ')}` : ''}`,
          disabled: occupied,
        };
      }),
    ],
    false
  );
}

function updateTeacherOptions(currentTeacherId = null, timeslotId = null, explicitCourseId = null) {
  const courseId = explicitCourseId != null ? explicitCourseId : Number(els.courseSelect.value);
  const course = (state.data.courses || []).find(c => c.id === courseId);
  let teachers = state.data.teachers || [];
  if (course) {
    const allowedIds = (state.data.teacher_ids_by_tag || {})[course.course_tag_id] || [];
    if (allowedIds.length) {
      teachers = teachers.filter(t => allowedIds.includes(t.id));
    }
  }
  if (timeslotId == null && state.selected && state.selected.length) {
    timeslotId = state.selected[0].timeslotId;
  }
  let teacherOptions = [{ value: '', label: 'No teacher' }];
  const teacherScheduleSummaries = buildTeacherScheduleSummaries();
  if (timeslotId != null) {
    const { occupiedTeacherIds, teacherConflictsById } = getTimeslotOccupancy(timeslotId);
    teacherOptions = [
      { value: '', label: 'No teacher' },
      ...teachers.map(t => {
        const conflicts = teacherConflictsById[t.id] || [];
        const occupied = occupiedTeacherIds.has(t.id) && t.id !== currentTeacherId;
        return {
          value: t.id,
          label: `${t.name}${conflicts.length ? ` — occupied by ${conflicts.join(', ')}` : ''}`,
          title: teacherScheduleSummaries[t.id] || 'No scheduled classes for this teacher.',
          disabled: occupied,
        };
      }),
    ];
  } else {
    teacherOptions = [{ value: '', label: 'No teacher' }, ...teachers.map(t => ({
      value: t.id,
      label: t.name,
      title: teacherScheduleSummaries[t.id] || 'No scheduled classes for this teacher.',
    }))];
  }
  fillSelect(els.teacherSelect, teacherOptions, false);
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
  const payloadMode = mode;
  const payload = {
    timeslot_id: selected[0].timeslotId,
    target_group_ids: targetGroupIds,
    mode: payloadMode,
    course_id: Number(formData.get('course_id')),
    teacher_id: toNullableNumber(formData.get('teacher_id')),
    room_id: toNullableNumber(formData.get('room_id')),
    study_program_ids: payloadMode === 'program' ? selectedProgramIds : [],
    expected_size: toNullableNumber(formData.get('expected_size')),
    notes: formData.get('notes') || null,
  };
  if (!validateClassModeSelection()) return;
  // Allow teacher conflict only for program classes when the same teacher+room is used
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
    const tagText = group.group_tag ? `${group.group_tag.code || ''}${group.group_tag.name ? ` — ${group.group_tag.name}` : ''}` : '';
    const label = document.createElement('label');
    label.className = 'checkbox-card';
    label.innerHTML = `
      <input type="checkbox" name="${groupName}" value="${group.id}" ${disabled ? 'disabled' : ''} />
      <span>${escapeHtml(group.code + (group.name ? ` — ${group.name}` : ''))}</span>
      ${tagText ? `<small>Group tag: ${escapeHtml(tagText)}</small>` : ''}
    `;
    container.appendChild(label);
  });
}

function renderTeacherCheckboxes(container, teachers, groupName) {
  if (!container) return;
  container.innerHTML = '';
  const tagMap = new Map((state.data.course_tags || []).map(tag => [tag.id, tag.name]));
  teachers.forEach(teacher => {
    const courseTags = (teacher.course_tag_ids || []).map(id => tagMap.get(id)).filter(Boolean);
    const label = document.createElement('label');
    label.className = 'checkbox-card';
    label.innerHTML = `
      <input type="checkbox" name="${groupName}" value="${teacher.id}" />
      <span>${escapeHtml(teacher.name)}</span>
      ${courseTags.length ? `<small>Course tags: ${escapeHtml(courseTags.join(', '))}</small>` : ''}
    `;
    container.appendChild(label);
  });
}

function renderGroupCheckboxesByTag(container, groups, groupName) {
  if (!container) return;
  container.innerHTML = '';
  const groupsByTag = new Map();
  groups.forEach(group => {
    const tagName = group.group_tag ? `${group.group_tag.code || ''}${group.group_tag.name ? ` — ${group.group_tag.name}` : ''}`.trim() : 'No group tag';
    if (!groupsByTag.has(tagName)) {
      groupsByTag.set(tagName, []);
    }
    groupsByTag.get(tagName).push(group);
  });

  groupsByTag.forEach((tagGroups, tagName) => {
    const section = document.createElement('section');
    section.className = 'checkbox-section';
    section.innerHTML = `<h4>${escapeHtml(tagName)}</h4>`;
    const sectionGrid = document.createElement('div');
    sectionGrid.className = 'checkbox-grid';
    tagGroups.forEach(group => {
      const label = document.createElement('label');
      label.className = 'checkbox-card';
      label.innerHTML = `
        <input type="checkbox" name="${groupName}" value="${group.id}" />
        <span>${escapeHtml(group.code + (group.name ? ` — ${group.name}` : ''))}</span>
      `;
      sectionGrid.appendChild(label);
    });
    section.appendChild(sectionGrid);
    container.appendChild(section);
  });
}

function renderGroupTagCheckboxes(container, groupTags, groupName) {
  if (!container) return;
  container.innerHTML = '';
  groupTags.forEach(tag => {
    const label = document.createElement('label');
    label.className = 'checkbox-card';
    label.innerHTML = `
      <input type="checkbox" name="${groupName}" value="${tag.id}" />
      <span>${escapeHtml(tag.code || tag.name || 'Group tag')}</span>
      ${tag.name && tag.name !== tag.code ? `<small>${escapeHtml(tag.name)}</small>` : ''}
    `;
    container.appendChild(label);
  });
}

function openExportGroupTagModal() {
  if (!els.exportGroupTagModal || !els.exportGroupTagOptions) return;
  if (!(state.data.group_tags || []).length) {
    alert('No group tags available to export.');
    return;
  }
  renderGroupTagCheckboxes(els.exportGroupTagOptions, state.data.group_tags || [], 'exportGroupTags');
  openModal('exportGroupTagModal');
}

async function submitExportGroupTagForm(e) {
  e.preventDefault();
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  const groupTagIds = collectCheckedValues(els.exportGroupTagOptions);
  if (!groupTagIds.length) {
    alert('Select at least one group tag.');
    return;
  }
  const params = groupTagIds.map(id => `group_tag_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  closeModal('exportGroupTagModal');
  await downloadExcel(url, 'Exporting group tags...');
}

function renderTeacherCheckboxesByCourseTag(container, teachers, groupName) {
  if (!container) return;
  container.innerHTML = '';
  const tagMap = new Map((state.data.course_tags || []).map(tag => [tag.id, tag.name]));
  const teachersByTag = new Map();

  teachers.forEach(teacher => {
    const tagIds = teacher.course_tag_ids || [];
    if (!tagIds.length) {
      if (!teachersByTag.has('No course tag')) teachersByTag.set('No course tag', []);
      teachersByTag.get('No course tag').push(teacher);
      return;
    }
    tagIds.forEach(tagId => {
      const tagName = tagMap.get(tagId) || 'Unknown tag';
      if (!teachersByTag.has(tagName)) teachersByTag.set(tagName, []);
      teachersByTag.get(tagName).push(teacher);
    });
  });

  teachersByTag.forEach((tagTeachers, tagName) => {
    const section = document.createElement('section');
    section.className = 'checkbox-section';
    section.innerHTML = `<h4>${escapeHtml(tagName)}</h4>`;
    const sectionGrid = document.createElement('div');
    sectionGrid.className = 'checkbox-grid';
    tagTeachers.forEach(teacher => {
      const label = document.createElement('label');
      label.className = 'checkbox-card';
      label.innerHTML = `
        <input type="checkbox" name="${groupName}" value="${teacher.id}" />
        <span>${escapeHtml(teacher.name)}</span>
      `;
      sectionGrid.appendChild(label);
    });
    section.appendChild(sectionGrid);
    container.appendChild(section);
  });
}

function renderCourseCheckboxesByTag(container, courses, groupName) {
  if (!container) return;
  container.innerHTML = '';
  const tagMap = new Map((state.data.course_tags || []).map(tag => [tag.id, tag.name]));
  const coursesByTag = new Map();

  courses.forEach(course => {
    const tagName = course.course_tag ? `${course.course_tag.code || ''}${course.course_tag.name ? ` — ${course.course_tag.name}` : ''}`.trim() : (tagMap.get(course.course_tag_id) || 'No course tag');
    const normalizedTag = tagName || 'No course tag';
    if (!coursesByTag.has(normalizedTag)) coursesByTag.set(normalizedTag, []);
    coursesByTag.get(normalizedTag).push(course);
  });

  coursesByTag.forEach((tagCourses, tagName) => {
    const section = document.createElement('section');
    section.className = 'checkbox-section';
    section.innerHTML = `<h4>${escapeHtml(tagName)}</h4>`;
    const sectionGrid = document.createElement('div');
    sectionGrid.className = 'checkbox-grid';
    tagCourses.forEach(course => {
      const label = document.createElement('label');
      label.className = 'checkbox-card';
      label.innerHTML = `
        <input type="checkbox" name="${groupName}" value="${course.id}" />
        <span>${escapeHtml(`${course.code || course.name || 'Course'}`)}</span>
        ${course.name && course.code ? `<small>${escapeHtml(course.name)}</small>` : ''}
      `;
      sectionGrid.appendChild(label);
    });
    section.appendChild(sectionGrid);
    container.appendChild(section);
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

function getDeployedCourseCountsForGroup(groupId) {
  const counts = {};
  const cells = state.data.cells || {};
  Object.values(cells).forEach(groupMap => {
    const items = groupMap[String(groupId)] || [];
    items.forEach(item => {
      if (!item.course_id) return;
      const key = Number(item.course_id);
      counts[key] = (counts[key] || 0) + 1;
    });
  });
  return counts;
}

function allGroupsForPrograms(programIds) {
  if (!programIds.length) return [];
  return (state.data.groups || [])
    .filter(group => programIds.some(pid => group.programs.some(p => p.id === pid)))
    .map(group => group.id);
}

function updateClassGroupOptions() {
  if (!els.classGroupOptions || !els.classForm) return;
  const mode = els.classForm.querySelector('input[name="mode"]:checked')?.value;
  const selectedProgramIds = collectCheckedValues(els.classProgramOptions);

  let visibleGroups = state.data.groups || [];
  if (mode === 'program' && selectedProgramIds.length > 0) {
    visibleGroups = visibleGroups.filter(group => selectedProgramIds.some(pid => group.programs.some(p => p.id === pid)));
  }

  const currentlyChecked = getClassGroupIds();
  renderGroupCheckboxes(els.classGroupOptions, visibleGroups, 'classGroups');

  const selectedGroupIds = currentlyChecked.length
    ? currentlyChecked.filter(id => visibleGroups.some(group => group.id === id))
    : state.selected.map(item => item.groupId).filter(id => visibleGroups.some(group => group.id === id));
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
    if (option.disabled) {
      opt.disabled = true;
    }
    if (option.selected) {
      opt.selected = true;
    }
    if (option.title) {
      opt.title = option.title;
    }
    selectEl.appendChild(opt);
  });
}

function buildTeacherScheduleSummaries() {
  const timeslotMap = new Map((state.data.timeslots || []).map(ts => [String(ts.id), ts]));
  const groupMap = new Map((state.data.groups || []).map(g => [String(g.id), g]));
  const teacherEntries = new Map();
  const cells = state.data.cells || {};

  Object.entries(cells).forEach(([timeslotId, groups]) => {
    const timeslot = timeslotMap.get(timeslotId);
    if (!timeslot || typeof groups !== 'object' || groups === null) return;
    Object.entries(groups).forEach(([groupId, items]) => {
      if (!Array.isArray(items)) return;
      const groupCode = groupMap.get(groupId)?.code || '';
      items.forEach(item => {
        const teacherId = item.teacher_id;
        if (teacherId == null) return;
        const entries = teacherEntries.get(teacherId) || [];
        entries.push({
          weekday: String(timeslot.weekday || ''),
          sort_order: Number(timeslot.sort_order) || 0,
          timeslot: String(timeslot.label || ''),
          course_name: String(item.course_name || item.course_code || ''),
          group_code: groupCode,
          room_name: String(item.room_name || ''),
        });
        teacherEntries.set(teacherId, entries);
      });
    });
  });

  const summaries = {};
  const weekdayShort = weekday => {
    const mapping = { MONDAY: 'Mon', TUESDAY: 'Tue', WEDNESDAY: 'Wed', THURSDAY: 'Thu', FRIDAY: 'Fri' };
    return mapping[weekday] || weekday;
  };

  const shortenTimeslot = label => String(label || '')
    .replace(/^German\s*/i, '')
    .replace(/\s*-\s*/g, '-')
    .trim();

  const weekdaySortOrder = { MONDAY: 0, TUESDAY: 1, WEDNESDAY: 2, THURSDAY: 3, FRIDAY: 4 };
  teacherEntries.forEach((entries, teacherId) => {
    entries.sort((a, b) => {
      const wa = weekdaySortOrder[a.weekday] ?? 99;
      const wb = weekdaySortOrder[b.weekday] ?? 99;
      return wa - wb || a.sort_order - b.sort_order || a.timeslot.localeCompare(b.timeslot) || a.room_name.localeCompare(b.room_name);
    });
    const grouped = new Map();
    entries.forEach(entry => {
      const key = `${entry.weekday}||${entry.timeslot}||${entry.room_name}`;
      const existing = grouped.get(key) || {
        weekday: entry.weekday,
        sort_order: entry.sort_order,
        timeslot: entry.timeslot,
        room_name: entry.room_name,
        courses: new Set(),
        groups: new Set(),
      };
      if (entry.course_name) existing.courses.add(entry.course_name);
      if (entry.group_code) existing.groups.add(entry.group_code);
      grouped.set(key, existing);
    });

    const header = 'Day | Time | Course | Group | Room';
    const lines = Array.from(grouped.values()).map(entry => {
      const course = entry.courses.size ? Array.from(entry.courses).sort().join(', ') : '-';
      const group = entry.groups.size ? Array.from(entry.groups).sort().join(', ') : '-';
      const room = entry.room_name || '-';
      return `${weekdayShort(entry.weekday)} | ${shortenTimeslot(entry.timeslot)} | ${course} | ${group} | ${room}`;
    });
    summaries[teacherId] = [header, ...lines].join('\n');
  });

  return summaries;
}

function collectCheckedValues(container) {
  return [...container.querySelectorAll('input[type="checkbox"]:checked')].map(input => Number(input.value));
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  document.querySelectorAll('.modal').forEach(m => {
    if (!m.classList.contains('hidden')) {
      m.style.zIndex = '1000';
    }
  });
  modal.style.zIndex = '1100';
  modal.classList.remove('hidden');
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.classList.add('hidden');
  modal.style.zIndex = '';
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
    const raw = await res.text();
    if (raw) {
      return { detail: raw.trim() };
    }
    return { detail: res.statusText || `HTTP ${res.status}` };
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

function openExportGroupModal() {
  if (!els.exportGroupModal || !els.exportGroupOptions) return;
  if (!(state.data.groups || []).length) {
    alert('No groups available to export.');
    return;
  }
  renderGroupCheckboxesByTag(els.exportGroupOptions, state.data.groups || [], 'exportGroups');
  openModal('exportGroupModal');
}

function openExportTeacherModal() {
  if (!els.exportTeacherModal || !els.exportTeacherOptions) return;
  if (!(state.data.teachers || []).length) {
    alert('No teachers available to export.');
    return;
  }
  renderTeacherCheckboxesByCourseTag(els.exportTeacherOptions, state.data.teachers || [], 'exportTeachers');
  openModal('exportTeacherModal');
}

function openExportCourseModal() {
  if (!els.exportCourseModal || !els.exportCourseOptions) return;
  if (!(state.data.courses || []).length) {
    alert('No courses available to export.');
    return;
  }
  renderCourseCheckboxesByTag(els.exportCourseOptions, state.data.courses || [], 'exportCourses');
  openModal('exportCourseModal');
}

function openExportAllCourse() {
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  const courses = state.data.courses || [];
  if (!courses.length) {
    alert('No courses available to export.');
    return;
  }
  const courseIds = [...new Set(courses.map(c => Number(c.id)).filter(Boolean))];
  if (!courseIds.length) {
    alert('No courses available to export.');
    return;
  }
  const params = courseIds.map(id => `course_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  downloadExcel(url, 'Exporting all courses...');
}

async function submitExportCourseForm(e) {
  e.preventDefault();
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  let courseIds = collectCheckedValues(els.exportCourseOptions);
  if (!courseIds.length) {
    alert('Select at least one course.');
    return;
  }
  courseIds = [...new Set(courseIds)];
  const params = courseIds.map(id => `course_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  closeModal('exportCourseModal');
  await downloadExcel(url, 'Exporting courses...');
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

async function submitExportGroupForm(e) {
  e.preventDefault();
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  const groupIds = collectCheckedValues(els.exportGroupOptions);
  if (!groupIds.length) {
    alert('Select at least one group.');
    return;
  }
  const params = groupIds.map(id => `group_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  closeModal('exportGroupModal');
  await downloadExcel(url, 'Exporting groups...');
}

function openExportAllGroup() {
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  const groups = state.data.groups || [];
  if (!groups.length) {
    alert('No groups available to export.');
    return;
  }
  const groupIds = [...new Set(groups.map(g => Number(g.id)).filter(Boolean))];
  if (!groupIds.length) {
    alert('No groups available to export.');
    return;
  }
  const params = groupIds.map(id => `group_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  downloadExcel(url, 'Exporting all groups...');
}

function openExportAllTeacher() {
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  const teachers = state.data.teachers || [];
  if (!teachers.length) {
    alert('No teachers available to export.');
    return;
  }
  const teacherIds = [...new Set(teachers.map(t => Number(t.id)).filter(Boolean))];
  if (!teacherIds.length) {
    alert('No teachers available to export.');
    return;
  }
  const params = teacherIds.map(id => `teacher_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  downloadExcel(url, 'Exporting all teachers...');
}

async function submitExportTeacherForm(e) {
  e.preventDefault();
  if (!state.timetableId) {
    alert('Select a timetable first.');
    return;
  }
  let teacherIds = collectCheckedValues(els.exportTeacherOptions);
  if (!teacherIds.length) {
    alert('Select at least one teacher.');
    return;
  }
  teacherIds = [...new Set(teacherIds)];
  const params = teacherIds.map(id => `teacher_ids=${id}`).join('&');
  const url = `/export.xlsx?timetable_id=${state.timetableId}&${params}`;
  closeModal('exportTeacherModal');
  await downloadExcel(url, 'Exporting teachers...');
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

function downloadTemplate(entity) {
  if (!entity) return;
  downloadExcel(`/template/${entity}.xlsx`, `Downloading ${entity.replace('-', ' ')} template...`);
}

function openUploadDialog(entity) {
  if (!entity || !els.entityUploadInput) return;
  currentImportEntity = entity;
  els.entityUploadInput.value = '';
  els.entityUploadInput.click();
}

async function handleEntityUpload(event) {
  if (!currentImportEntity) return;
  const file = event.target.files?.[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  if (els.entityUploadMessage) {
    els.entityUploadMessage.className = 'upload-message info';
    els.entityUploadMessage.textContent = `Uploading ${currentImportEntity.replace('-', ' ')}...`;
  }
  const params = [];
  if (state.timetableId != null) {
    params.push(`timetable_id=${state.timetableId}`);
  } else if (state.selectedCycleId != null) {
    params.push(`cycle_id=${state.selectedCycleId}`);
  }
  const url = `/api/import/${currentImportEntity}${params.length ? `?${params.join('&')}` : ''}`;
  try {
    const res = await fetch(url, {
      method: 'POST',
      body: formData,
    });
    const data = await safeJson(res);
    if (!res.ok) {
      if (els.entityUploadMessage) {
        els.entityUploadMessage.className = 'upload-message error';
        els.entityUploadMessage.textContent = `Import failed for ${currentImportEntity.replace('-', ' ')}.`;
      }
      alert('Import failed: ' + formatError(data));
      return;
    }
    if (els.entityUploadMessage) {
      els.entityUploadMessage.className = 'upload-message success';
      els.entityUploadMessage.textContent = `Imported ${currentImportEntity.replace('-', ' ')} successfully.`;
    }
    await refreshData(state.timetableId, state.selectedCycleId);
  } finally {
    currentImportEntity = null;
    if (els.entityUploadInput) {
      els.entityUploadInput.value = '';
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
  (state.data.courses || [])
    .filter(c => !c.elective)
    .slice()
    .sort((a, b) => String(a.code || a.name || '').localeCompare(String(b.code || b.name || '')))
    .forEach(course => {
      const opt = document.createElement('option');
      opt.value = course.id;
      opt.textContent = course.code ? `${course.code} — ${course.name}` : course.name;
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
  refreshRequirementsModalIfOpen();
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
  (state.data.courses || [])
    .slice()
    .sort((a, b) => String(a.code || a.name || '').localeCompare(String(b.code || b.name || '')))
    .forEach(course => {
      const opt = document.createElement('option');
      opt.value = course.id;
      opt.textContent = course.code ? `${course.code} — ${course.name}` : course.name;
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
  if (state.timetableId) {
    url += `?timetable_id=${state.timetableId}`;
  }
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) {
    alert('Failed to delete requirement');
    return;
  }
  await refreshData(state.timetableId);
  refreshRequirementsModalIfOpen();
}
