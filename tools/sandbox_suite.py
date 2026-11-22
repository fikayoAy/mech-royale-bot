"""In-container harness, called by validate_sandbox.py; writes only /tmp."""
from contextlib import redirect_stdout,redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import unittest

ROOT=Path('/suite');sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,'/bot')
import bot


def main():
    log=io.StringIO();errors=io.StringIO();passed=True
    # Test modules respect MECH_RUNTIME_DIR, so the immutable image is what runs.
    with redirect_stdout(log),redirect_stderr(errors):
        suite=unittest.defaultTestLoader.discover('/suite/tests')
        result=unittest.TextTestRunner(stream=log,verbosity=1).run(suite);passed=result.wasSuccessful()
        import strictness_runner
        sys.argv=['strictness_runner','--all','--seed','17','--seed','29','--reports-dir','/tmp/reports']
        try:strictness_runner.main()
        except SystemExit as exc:passed=passed and not exc.code
    reports={p.name:(json.loads(p.read_text()) if p.suffix=='.json' else p.read_text()) for p in Path('/tmp/reports').glob('*')}
    proc_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    value={'architecture':platform.machine(),'uid':os.getuid(),'runtime_module':bot.__file__,
           'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('/bot').glob('*.py'))},
           'peak_rss_bytes':proc_peak,'unit_tests':result.testsRun,'unit_failures':len(result.failures)+len(result.errors),
           'passed':passed,'log':log.getvalue(),'diagnostics':errors.getvalue(),'reports':reports}
    print(json.dumps(value));return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
