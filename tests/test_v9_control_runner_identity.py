import json
from pathlib import Path
import tempfile
import unittest
from tools.v9 import control_runner_identity as R


def data(version='20261023.334.3'):
    return json.dumps([dict(group='Operating System',detail='Ubuntu'),dict(group='Runner Image',detail=
        'Image: ubuntu-24.04\nVersion: '+version+'\nIncluded Software: https://github.com/actions/runner-images/blob/tag/readme\nImage Release: https://github.com/actions/runner-images/releases/tag/example')]).encode()


class Identity(unittest.TestCase):
    def test_official_group_detail_shape(self):
        self.assertEqual(R.image_fields(data())['Version'],'20261023.334.3')
        with self.assertRaises(ValueError):R.image_fields(b'{"ImageVersion":"20261023.334.3"}')

    def test_ambiguous_or_incomplete_image_records_refuse(self):
        record=json.loads(data())[1]
        for raw in (json.dumps([record,record]).encode(),b'[{"group":"Runner Image","group":"other","detail":"x"}]',
                    data().replace(b'Version: 20261023.334.3',b'Version: unknown'),
                    data().replace(b'Image: ubuntu-24.04',b'Image: ubuntu-24.04\\nImage: ubuntu-24.04')):
            with self.assertRaises(ValueError):R.image_fields(raw)

    def test_environment_filters_unrelated_values_and_refuses_duplicates(self):
        self.assertEqual(R.environment_fields(b'OTHER_SECRET=do-not-retain\nImageOS="ubuntu24"\nImageVersion=20261023.334.3\n'),
                         {'ImageOS':'ubuntu24','ImageVersion':'20261023.334.3'})
        for raw in (b'ImageOS=ubuntu24',b'ImageOS=ubuntu24\nImageOS=ubuntu24\nImageVersion=x',b'ImageOS="ubuntu24\nImageVersion=x'):
            with self.assertRaises(ValueError):R.environment_fields(raw)

    def test_conflict_and_agreement_never_grant_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'etc').mkdir();(root/'imagegeneration').mkdir()
            (root/'etc/environment').write_bytes(b'ImageOS=ubuntu24\nImageVersion=20261023.334.3\n')
            env=dict(ImageOS='ubuntu24',ImageVersion='20261023.334.3',RUNNER_OS='Linux',RUNNER_ARCH='X64')
            for version,status in [('20261012.334.1','CONFLICTING_IDENTITY_CLAIMS'),('20261023.334.3','CONSISTENT_CLAIMS_NOT_ATTESTED')]:
                (root/'imagegeneration/imagedata.json').write_bytes(data(version))
                report=R.collect(env,root)
                self.assertEqual(report['status'],status)
                self.assertFalse(report['resource_qualified']);self.assertFalse(report['promotion_authority'])

    def test_unavailable_and_oversize_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.assertEqual(R.collect({},root)['status'],'UNAVAILABLE')
            (root/'etc').mkdir();(root/'etc/environment').write_bytes(b'x'*(1024*1024+1))
            report=R.collect({},root)
            self.assertEqual(report['status'],'UNAVAILABLE')
            self.assertEqual(report['files']['/etc/environment']['error_type'],'ValueError')
