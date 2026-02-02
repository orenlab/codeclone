from codeclone.html_report import build_html_report

def test_html_report_smoke():
    func_groups = {
        "hash1": [
            {"qualname": "f1", "filepath": "a.py", "start_line": 1, "end_line": 10},
            {"qualname": "f2", "filepath": "b.py", "start_line": 1, "end_line": 10},
        ]
    }
    block_groups = {}
    
    # We need to mock _FileCache or create dummy files because _render_code_block reads files
    # Actually _render_code_block reads real files.
    # We can create dummy files.
    
    import pytest
    from pathlib import Path
    
    # Using pytest fixture directly in test function? No, need to pass it.
    
def test_html_report_generation(tmp_path):
    f1 = tmp_path / "a.py"
    f1.write_text("def f1():\n    pass\n")
    f2 = tmp_path / "b.py"
    f2.write_text("def f2():\n    pass\n")
    
    func_groups = {
        "hash1": [
            {"qualname": "f1", "filepath": str(f1), "start_line": 1, "end_line": 2},
            {"qualname": "f2", "filepath": str(f2), "start_line": 1, "end_line": 2},
        ]
    }
    
    html = build_html_report(
        func_groups=func_groups,
        block_groups={},
        title="Test Report"
    )
    
    assert "<!doctype html>" in html
    assert "Test Report" in html
    assert "f1" in html
    assert "f2" in html
    assert "svg" in html # Check if SVGs are present
