import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.v9 import control_dependency_lock as L


class Lock(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.wheels=self.root/'wheels';self.wheels.mkdir();self.out=self.root/'out'

    def wheel(self,filename='example.whl',metadata=b'Name: Example_Package\nVersion: 1.2.3\n\n'):
        path=self.wheels/filename
        with zipfile.ZipFile(path,'w') as z:z.writestr('example.dist-info/METADATA',metadata)
        return path

    def test_exact_wheel_bytes_bound_and_no_authority(self):
        p=self.wheel();r=L.build(self.wheels,self.out)
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        raw=('example-package==1.2.3 --hash=sha256:'+digest+'\n').encode()
        self.assertEqual((self.out/'requirements.lock').read_bytes(),raw)
        self.assertEqual(r['lock_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertFalse(r['resource_qualified']);self.assertFalse(r['promotion_authority'])
        with self.assertRaises(FileExistsError):L.build(self.wheels,self.out)

    def test_duplicate_normalized_packages_refuse_before_output(self):
        self.wheel();self.wheel('second.whl',b'Name: example-package\nVersion: 2\n\n')
        with self.assertRaises(ValueError):L.build(self.wheels,self.out)
        self.assertFalse(self.out.exists())

    def test_missing_ambiguous_and_unsafe_metadata_refuse(self):
        for raw in (b'Name: p\n\n',b'Name: p\nName: q\nVersion: 1\n\n',
                    b'Name: p\nVersion: 1 --extra-index-url=bad\n\n',b'Name: ../p\nVersion: 1\n\n'):
            self.wheel(metadata=raw)
            with self.subTest(raw=raw),self.assertRaises(ValueError):L.build(self.wheels,self.out)
            self.assertFalse(self.out.exists())

    def test_empty_nonwheel_and_multiple_metadata_refuse(self):
        with self.assertRaises(ValueError):L.build(self.wheels,self.out)
        p=self.wheels/'source.tar.gz';p.write_bytes(b'no source builds')
        with self.assertRaises(ValueError):L.build(self.wheels,self.out)
        p.unlink();p=self.wheel()
        with zipfile.ZipFile(p,'a') as z:z.writestr('other.dist-info/METADATA',b'Name: other\nVersion: 1\n\n')
        with self.assertRaises(ValueError):L.build(self.wheels,self.out)
