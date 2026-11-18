"""Exclusive, flushed Linux synthetic-probe progress receipts; never qualification."""
import hashlib
import json
import os
from pathlib import Path


def encoded(value):
    return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()


class Journal:
    def __init__(self,path,plan,bindings):
        self.root=Path(path)
        self.root.mkdir()  # Refuse any earlier directory, including an empty one.
        self._sync_directory(self.root.parent)
        self.completed=[]
        self._write('started.json',dict(status='STARTED',plan=plan,implementation_sha256=bindings))

    @staticmethod
    def _sync_directory(path):
        descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

    def _write(self,name,value):
        data=dict(schema='v9.a6-synthetic-progress/1',synthetic_only=True,
                  resource_qualified=False,promotion_authority=False,**value)
        raw=encoded(data);pending=self.root/(name+'.pending');target=self.root/name
        with pending.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        # Publish a complete inode without overwriting an earlier receipt.
        os.link(pending,target)
        pending.unlink()
        self._sync_directory(self.root)
        return dict(path=name,sha256=hashlib.sha256(raw).hexdigest())

    def begin(self,index,case):
        self._write('case-%03d.started.json'%index,dict(status='CASE_STARTED',index=index,case=case))

    def complete(self,index,measurement):
        receipt=self._write('case-%03d.completed.json'%index,
                            dict(status='CASE_MEASURED_NOT_QUALIFIED',index=index,measurement=measurement))
        self.completed.append(receipt)

    def finish(self,report):
        self._write('completed.json',dict(status='MEASUREMENTS_COMPLETED_NOT_FINAL_REPORT',
            completed_cases=self.completed,report_sha256=hashlib.sha256(encoded(report)).hexdigest()))

    def fail(self,error):
        self._write('failed.json',dict(status='FAILED_OR_INTERRUPTED',
            error_type=type(error).__name__,completed_cases=self.completed))
