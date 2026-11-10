import {test} from 'node:test';
import assert from 'node:assert/strict';
import {isInvoicedUnpaidCertificate} from './tracking-policy';
const certificate = {stage:'Certificate', consultant:'QAC', invoiced:'Yes', payment:'Unpaid'};
test('includes unpaid certificates without invoice reference or balance',()=>{
 assert.equal(isInvoicedUnpaidCertificate({...certificate,invoiceRef:'',balance:null}),true);
 assert.equal(isInvoicedUnpaidCertificate({...certificate,payment:'Part-paid'}),true);
});
test('excludes paid, uninvoiced, archived, pipeline and payment-only records',()=>{
 for(const patch of [{payment:'Paid'},{payment:''},{invoiced:'No'},{invoiced:''},{archived:true},{stage:'Decision'},{consultant:'Ender Karslı'}])
  assert.equal(isInvoicedUnpaidCertificate({...certificate,...patch}),false);
});
test('stale balances cannot override established payment status',()=>{
 assert.equal(isInvoicedUnpaidCertificate({...certificate,payment:'Paid',balance:100}),false);
 assert.equal(isInvoicedUnpaidCertificate({...certificate,balance:0}),true);
});
