import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clientRecords} from './client-records';

const client = {id:'one', kind:'certificate', company:'Example', country:'Germany', stage:'Certificate'};

test('client deletion includes hidden standards, stages, sites and consultants', () => {
  const rows = [client,
    {...client, id:'two', standard:'ISO 14001', stage:'Audit Planning', consultant:'Another'},
    {...client, id:'three', stage:'Application Received', site:'Branch'},
  ];
  assert.deepEqual(clientRecords(rows, client).map(r => r.id), ['one', 'two', 'three']);
});

test('client deletion excludes other legal names, countries, finance and archived records', () => {
  const rows = [client,
    {...client, id:'other-name', company:'Example Ltd'},
    {...client, id:'other-country', country:'France'},
    {...client, id:'archived', archived:true},
    {...client, id:'invoice', kind:'invoice'},
    {...client, id:'payment', kind:'other'},
  ];
  assert.deepEqual(clientRecords(rows, client), [client]);
  assert.equal(rows.length, 6);
  assert.equal(clientRecords([{...client, country:null}], {...client, country:''}).length, 1);
});
