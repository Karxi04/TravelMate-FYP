const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const template = fs.readFileSync(path.join(__dirname, '../modules/fr12_tourism_operator_management/templates/fr12_tourism_operator_management/booking_detail.html'), 'utf8');
const handlers = [...template.matchAll(/<form oninput="([^"]+)"/g)].map(match => match[1]);

test('every arrangement form clears editable confirmation when details change without submitting', () => {
  assert.equal(handlers.length, 3);
  for (const source of handlers) {
    const handler = new Function('event', source);
    const form = {elements: {attestation: {checked: true}}, submit() { assert.fail('No automatic submission'); }};
    for (const name of ['supplierName', 'providerName', 'notes', 'reference']) {
      form.elements.attestation.checked = true;
      handler.call(form, {target: {name}});
      assert.equal(form.elements.attestation.checked, false);
    }
    form.elements.attestation.checked = true;
    handler.call(form, {target: {name: 'attestation'}});
    assert.equal(form.elements.attestation.checked, true);
  }
});
