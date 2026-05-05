from pathlib import Path
path = Path(r'f:\timetable_db_app\app\static\script.js')
text = path.read_text(encoding='utf-8')
old = '''async function deleteRequirement(type, tagOrProgId, courseId) {
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
}
'''
new = '''async function deleteRequirement(type, tagOrProgId, courseId) {
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
'''
if old not in text:
    raise SystemExit('Old block not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('patched')
