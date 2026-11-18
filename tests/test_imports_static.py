"""The Qt modules never run outside QGIS: check statically that every internal import resolves."""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "elda_qgis").rglob("*.py"))


def module_file(dotted):
    base = ROOT.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def top_level_names(path):
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    return names


def internal_imports(path):
    package = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            base = package[: len(package) - node.level + 1] + (node.module.split(".") if node.module else [])
        elif (node.module or "").split(".")[0] == "elda_qgis":
            base = node.module.split(".")
        else:
            continue
        yield ".".join(base), [a.name for a in node.names]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_internal_imports_resolve(path):
    for base, names in internal_imports(path):
        target = module_file(base)
        assert target is not None, "%s: no module %s" % (path.name, base)
        defined = top_level_names(target)
        for name in names:
            assert name in defined or module_file(base + "." + name), "%s: %s has no %s" % (path.name, base, name)


def test_no_undefined_or_unused_name():
    from pyflakes.api import checkRecursive
    from pyflakes.reporter import Reporter
    import io

    out = io.StringIO()
    checkRecursive([str(ROOT / "elda_qgis")], Reporter(out, out))
    assert out.getvalue() == ""


def _attribute_events(init):
    """(line, column, name, is_store) for every `self.<name>` in a constructor, in source order."""
    events = []
    for node in ast.walk(init):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            events.append((node.lineno, node.col_offset, node.attr, isinstance(node.ctx, ast.Store)))
    return sorted(events)


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_constructors_never_read_an_attribute_they_set_later(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef) or node.name != "__init__":
            continue
        events = _attribute_events(node)
        stored_lines = {}
        for line, _col, name, is_store in events:
            if is_store:
                stored_lines.setdefault(name, line)
        for line, _col, name, is_store in events:
            first = stored_lines.get(name)
            # a nested function or lambda body runs later: only flag plain statements
            if not is_store and first is not None and line < first and not _inside_deferred(node, line):
                raise AssertionError("%s:%d reads self.%s before line %d sets it" % (path.name, line, name, first))


def _inside_deferred(init, line):
    for node in ast.walk(init):
        if node is not init and isinstance(node, (ast.FunctionDef, ast.Lambda)):
            if node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
                return True
    return False
