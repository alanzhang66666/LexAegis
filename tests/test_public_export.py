import importlib.util
from pathlib import Path

def scanner():
    spec=importlib.util.spec_from_file_location('export_scan_test',Path(__file__).resolve().parents[1]/'scripts/check_public_export.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def test_export_rejects_runtime_and_private_values_without_returning_them():
    module=scanner();value=b'only-a-temporary-test-private-value'
    issues=module.inspect_blob('docs/note.md',value,[value])
    assert issues==['private local value'] and value.decode() not in str(issues)
    assert module.inspect_blob('.data/private/accounts.json',b'{}')
    assert module.inspect_blob('deploy/runtime/gateway.env',b'KEY=')
    assert module.inspect_blob('models/model.gguf',b'fake model')
    assert not module.inspect_blob('deploy/example.env.example',b'LEX_CLOUD_PRIMARY_KEY=')

def test_export_detects_credential_shape_but_not_a_model_hash():
    module=scanner()
    assert module.inspect_blob('bad.py',b'sk-'+b'x'*32)==['credential-shaped token']
    assert not module.inspect_blob('manifest.example.json',b'"sha256:'+b'a'*64+b'"')

def test_archive_scan_checks_numeric_and_date_constants_not_only_names():
    module=scanner();name='deploy/workbench_demo/archive/example.py.txt'
    assert module.inspect_archive_literals(name,b'ARCHIVE\n\nrows=[("placeholder", 12345)]',{'12345'},set())
    assert module.inspect_archive_literals(name,b'ARCHIVE\n\ndate="2025-01-02"',set(),{'2025-01-02'})
    assert not module.inspect_archive_literals(name,b'ARCHIVE\n\nrows=[("placeholder", "<PRIVATE_NUMERIC>")]',{'12345'},set())
