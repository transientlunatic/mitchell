"""mitchell condor-dag: the generated DAG, and that running it builds the catalogue.

There is no HTCondor here, so the DAG is checked three ways: its structure is
parsed back, each submit description goes through HTCondor's own parser, and
the whole thing is *emulated*: the generated files are read back, macros
expanded as DAGMan would, and every node is run through the generated wrapper
script in its own scratch directory, with the file transfers applied by hand.
The emulation proves the commands are well formed and that parallel per-event
builds merge into the same catalogue as a sequential one.  It cannot prove
that a particular pool accepts the files.
"""

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner
from pesummary_h5 import make_pesummary_h5

from mitchell import MitchellStore, condor
from mitchell.cli import cli

EVENTS = ["GW000001_000000", "GW000002_000000", "GW000003_000000"]


# -- helpers -----------------------------------------------------------------


def run(*args, **kwargs):
    return CliRunner().invoke(cli, [str(a) for a in args], **kwargs)


def parse_dag(text: str) -> dict:
    """The parts of a .dag file the tests care about."""
    dag: dict = {
        "jobs": {},
        "vars": {},
        "retry": {},
        "category": {},
        "maxjobs": {},
        "pre": {},
        "edges": [],
    }
    for line in text.splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        keyword = words[0]
        if keyword == "JOB":
            dag["jobs"][words[1]] = words[2]
        elif keyword == "VARS":
            body = line.split(None, 2)[2]
            dag["vars"][words[1]] = dict(re.findall(r'(\w+)="([^"]*)"', body))
        elif keyword == "RETRY":
            dag["retry"][words[1]] = int(words[2])
        elif keyword == "CATEGORY":
            dag["category"][words[1]] = words[2]
        elif keyword == "SCRIPT":
            assert words[1] == "PRE"
            dag["pre"][words[2]] = words[3:]
        elif keyword == "MAXJOBS":
            dag["maxjobs"][words[1]] = int(words[2])
        elif keyword == "PARENT":
            split = words.index("CHILD")
            dag["edges"].append((words[1:split], words[split + 1 :]))
    return dag


def parse_submit(text: str) -> dict[str, str]:
    """``key = value`` lines of a submit description (``queue`` is kept as '')."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "queue":
            out["queue"] = ""
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def expand(value: str, macros: dict[str, str]) -> str:
    return re.sub(r"\$\((\w+)\)", lambda m: macros[m.group(1)], value)


def split_arguments(value: str) -> list[str]:
    """Undo HTCondor's new-syntax ``arguments`` quoting."""
    assert value.startswith('"'), value
    assert value.endswith('"'), value
    body, args, current, in_single, i = value[1:-1], [], "", False, 0
    while i < len(body):
        c = body[i]
        if in_single:
            if body[i : i + 2] in ("''", '""'):
                current += c
                i += 2
                continue
            if c == "'":
                in_single = False
            else:
                current += c
        elif c == "'":
            in_single = True
        elif c.isspace():
            if current:
                args.append(current)
                current = ""
        else:
            current += c
        i += 1
    if current:
        args.append(current)
    return args


@pytest.fixture
def mitchell_stub(tmp_path) -> str:
    """A stand-in for the ``mitchell`` console script that works anywhere."""
    stub = tmp_path / "bin" / "mitchell"
    stub.parent.mkdir()
    stub.write_text(
        f"#!/bin/bash\nexec {shlex.quote(sys.executable)} -c "
        '"from mitchell.cli import cli; cli()" "$@"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return str(stub)


@pytest.fixture
def h5_dir(tmp_path) -> Path:
    directory = tmp_path / "h5"
    directory.mkdir()
    for name in EVENTS:
        make_pesummary_h5(directory / f"IGWN-GWTC2p1-v2-{name}_PEDataRelease.h5")
    return directory


def generate(tmp_path, h5_dir, mitchell_stub, *extra) -> Path:
    result = run(
        "condor-dag",
        tmp_path / "dag",
        tmp_path / "catalogue.zarr",
        "--h5-dir",
        h5_dir,
        "--mitchell",
        mitchell_stub,
        *extra,
    )
    assert result.exit_code == 0, result.output
    return tmp_path / "dag"


# -- generated files ---------------------------------------------------------


def test_dag_structure(tmp_path, h5_dir, mitchell_stub):
    dag_dir = generate(tmp_path, h5_dir, mitchell_stub)
    dag = parse_dag((dag_dir / "catalogue.dag").read_text())

    converts = [f"convert_{name}" for name in EVENTS]
    assert sorted(n for n in dag["jobs"] if n != "combine") == converts
    assert {dag["jobs"][n] for n in converts} == {"convert_h5.sub"}
    assert dag["jobs"]["combine"] == "combine.sub"
    for name, node in zip(EVENTS, converts, strict=True):
        assert dag["vars"][node]["event"] == name
        assert dag["vars"][node]["part"] == f"parts/{name}.zarr"
        assert dag["vars"][node]["h5file"].endswith(".h5")
        assert Path(dag["vars"][node]["h5"]).is_absolute()
        assert dag["retry"][node] == condor.DEFAULT_RETRIES
        assert dag["category"][node] == "convert"
        assert dag["pre"][node] == ["/bin/rm", "-rf", f"parts/{name}.zarr"]
    # The merge runs only after every conversion.
    assert dag["edges"] == [(converts, ["combine"])]
    # Condor will not create the directories it writes into.
    assert (dag_dir / "parts").is_dir()
    assert (dag_dir / "logs").is_dir()


def test_submit_files_parse_with_htcondor(tmp_path, h5_dir, mitchell_stub):
    htcondor2 = pytest.importorskip("htcondor2")
    dag_dir = generate(tmp_path, h5_dir, mitchell_stub)
    macros = {
        "event": EVENTS[0],
        "part": f"parts/{EVENTS[0]}.zarr",
        "h5": "/data/x.h5",
        "h5file": "x.h5",
        "JOB": "n",
    }
    for name in ("convert_h5.sub", "combine.sub"):
        text = (dag_dir / name).read_text()
        # DAGMan supplies the macros via VARS; define them in the file instead.
        sub = htcondor2.Submit(
            "".join(f"{k} = {v}\n" for k, v in macros.items()) + text
        )
        assert sub["executable"] == "run_mitchell.sh"
        assert "queue" in text
    convert = htcondor2.Submit(
        "".join(f"{k} = {v}\n" for k, v in macros.items())
        + (dag_dir / "convert_h5.sub").read_text()
    )
    assert split_arguments(convert.expand("arguments")) == [
        "from-pesummary",
        "x.h5",
        "part.zarr",
        "--event-name",
        EVENTS[0],
    ]
    assert convert.expand("transfer_output_remaps").strip('"') == (
        f"part.zarr = parts/{EVENTS[0]}.zarr"
    )
    assert convert["request_memory"] == condor.DEFAULT_MEMORY


def test_combine_runs_locally_and_moves_parts(tmp_path, h5_dir, mitchell_stub):
    dag_dir = generate(tmp_path, h5_dir, mitchell_stub)
    combine = parse_submit((dag_dir / "combine.sub").read_text())
    assert combine["universe"] == "local"
    assert split_arguments(combine["arguments"]) == [
        "combine",
        str((tmp_path / "catalogue.zarr").resolve()),
        "--parts-dir",
        "parts",
        "--move",
    ]


def test_wrapper_sends_the_gwresults_cache_to_scratch(tmp_path):
    """Workers often have no writable home; downloads must not land there."""
    stub = tmp_path / "show-env"
    stub.write_text('#!/bin/bash\necho "$XDG_CACHE_HOME"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    wrapper = tmp_path / "run_mitchell.sh"
    wrapper.write_text(condor.wrapper_script(str(stub)))
    wrapper.chmod(0o755)

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {**os.environ, "_CONDOR_SCRATCH_DIR": str(scratch)}
    out = subprocess.run(  # noqa: S603 - runs the wrapper under test
        [str(wrapper)], capture_output=True, text=True, env=env, check=True
    ).stdout.strip()
    assert out == str(scratch / "xdg-cache")


def test_a_job_that_cannot_start_still_returns_its_output_directory(tmp_path):
    """Otherwise Condor holds the job (output file missing) and the DAG stalls."""
    wrapper = tmp_path / "run_mitchell.sh"
    wrapper.write_text(condor.wrapper_script("/nonexistent/worker/mitchell"))
    wrapper.chmod(0o755)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {**os.environ, "_CONDOR_SCRATCH_DIR": str(scratch)}

    result = subprocess.run(  # noqa: S603
        [str(wrapper), "from-gwtc", "part.zarr"],
        cwd=scratch,
        env={**env, "MITCHELL_ENSURE_DIR": "part.zarr"},
        capture_output=True,
    )

    assert result.returncode != 0  # the node fails, so DAGMan retries it
    assert (scratch / "part.zarr").is_dir()  # ...and there is something to transfer


def test_conversion_nodes_ask_for_the_output_directory_to_be_ensured(
    tmp_path, h5_dir, mitchell_stub
):
    dag_dir = generate(tmp_path, h5_dir, mitchell_stub)
    convert = parse_submit((dag_dir / "convert_h5.sub").read_text())
    assert convert["environment"] == '"MITCHELL_ENSURE_DIR=part.zarr"'
    combine = parse_submit((dag_dir / "combine.sub").read_text())
    assert "environment" not in combine  # it must not create part.zarr


def test_stale_parts_from_a_failed_attempt_are_cleared_before_a_retry(
    tmp_path, h5_dir, mitchell_stub
):
    dag_dir = generate(tmp_path, h5_dir, mitchell_stub)
    stale = dag_dir / "parts" / f"{EVENTS[0]}.zarr"
    stale.mkdir()
    (stale / "left-by-a-failed-attempt.txt").write_text("partial")

    emulate_dag(dag_dir, mitchell_stub)  # asserts the PRE script cleared it

    built = MitchellStore.open(tmp_path / "catalogue.zarr", mode="r")
    assert [e.name for e in built] == EVENTS
    assert not (
        tmp_path
        / "catalogue.zarr"
        / "events"
        / EVENTS[0]
        / "left-by-a-failed-attempt.txt"
    ).exists()


@pytest.mark.parametrize(
    "args",
    [
        ["from-gwtc", "part.zarr", "--event", "GW150914_095045"],
        ["from-pesummary", "my file.h5", "part.zarr"],
        ["x", "it's", 'say "hi"'],
    ],
)
def test_arguments_quoting_round_trips(args):
    assert split_arguments(condor.quote_arguments(args)) == args


# -- running the DAG (emulated) ----------------------------------------------


def emulate_dag(dag_dir: Path, mitchell_stub: str) -> None:
    """Run every node as Condor would: scratch dir, transfers, wrapper script."""
    dag = parse_dag((dag_dir / "catalogue.dag").read_text())
    (dag_dir / "logs").mkdir(exist_ok=True)

    def run_job(submit_name: str, macros: dict[str, str], cwd: Path) -> None:
        sub = parse_submit((dag_dir / submit_name).read_text())
        args = split_arguments(expand(sub["arguments"], macros))
        subprocess.run(  # noqa: S603 - runs the generated wrapper
            [str(dag_dir / sub["executable"]), *args],
            cwd=cwd,
            env={**os.environ, "_CONDOR_SCRATCH_DIR": str(cwd)},
            check=True,
            capture_output=True,
        )

    converts = [n for n in dag["jobs"] if n != "combine"]
    for node in converts:
        macros = {**dag["vars"][node], "JOB": node}
        subprocess.run(dag["pre"][node], cwd=dag_dir, check=True)  # noqa: S603
        assert not (dag_dir / macros["part"]).exists()  # stale parts are cleared
        scratch = dag_dir / "scratch" / node
        scratch.mkdir(parents=True)
        sub = parse_submit((dag_dir / dag["jobs"][node]).read_text())
        if "transfer_input_files" in sub:  # Condor copies inputs to the scratch dir
            source = Path(expand(sub["transfer_input_files"], macros))
            shutil.copy(source, scratch / source.name)
        run_job(dag["jobs"][node], macros, scratch)
        # ... and sends transfer_output_files back, remapped.
        wanted, target = (
            expand(sub["transfer_output_remaps"], macros).strip('"').split("=")
        )
        assert sub["transfer_output_files"] == wanted.strip()
        shutil.move(scratch / wanted.strip(), dag_dir / target.strip())

    run_job("combine.sub", {"JOB": "combine"}, dag_dir)  # runs where it is submitted


def test_emulated_dag_builds_the_same_catalogue_as_a_sequential_run(
    tmp_path, h5_dir, mitchell_stub
):
    dag_dir = generate(tmp_path, h5_dir, mitchell_stub)
    emulate_dag(dag_dir, mitchell_stub)

    sequential = tmp_path / "sequential.zarr"
    for path in sorted(h5_dir.glob("*.h5")):
        name = re.search(r"GW\d{6}_\d{6}", path.name).group()
        MitchellStore.from_pesummary_h5(path, name, sequential, mode="a")

    built = MitchellStore.open(tmp_path / "catalogue.zarr", mode="r")
    expected = MitchellStore.open(sequential, mode="r")
    assert [e.name for e in built] == EVENTS
    assert built._index() == expected._index()
    assert not list((dag_dir / "parts").glob("*.zarr"))  # consumed by --move


def test_emulated_dag_adds_only_new_events_to_an_existing_catalogue(
    tmp_path, h5_dir, mitchell_stub
):
    first = h5_dir / f"IGWN-GWTC2p1-v2-{EVENTS[0]}_PEDataRelease.h5"
    MitchellStore.from_pesummary_h5(first, EVENTS[0], tmp_path / "catalogue.zarr")

    dag_dir = generate(
        tmp_path, h5_dir, mitchell_stub
    )  # --skip-existing is the default
    dag = parse_dag((dag_dir / "catalogue.dag").read_text())
    assert sorted(dag["vars"][n]["event"] for n in dag["vars"]) == EVENTS[1:]

    emulate_dag(dag_dir, mitchell_stub)
    built = MitchellStore.open(tmp_path / "catalogue.zarr", mode="r")
    assert [e.name for e in built] == EVENTS


# -- the gwtc source ---------------------------------------------------------


@pytest.fixture
def stub_gwresults(tmp_path, monkeypatch):
    """A fake gwresults whose 'downloads' are copies of a synthetic file."""
    source = tmp_path / "source.h5"
    make_pesummary_h5(source)
    names = ["GWfake_000000", "GWfake_111111", "GWfake_222222"]

    package = types.ModuleType("gwresults")
    registry = types.ModuleType("gwresults.registry")
    cache = types.ModuleType("gwresults.cache")
    registry.list_events = lambda catalogue=None: list(names)

    def fetch(event: str) -> str:
        path = tmp_path / "downloads" / f"{event}.h5"
        path.parent.mkdir(exist_ok=True)
        shutil.copy(source, path)
        return str(path)

    cache.fetch = fetch
    package.registry, package.cache = registry, cache
    for name, module in (
        ("gwresults", package),
        ("gwresults.registry", registry),
        ("gwresults.cache", cache),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return names


def test_gwtc_dag_uses_from_gwtc_and_throttles_downloads(
    tmp_path, mitchell_stub, stub_gwresults
):
    result = run(
        "condor-dag",
        tmp_path / "dag",
        tmp_path / "catalogue.zarr",
        "--gwtc",
        "--mitchell",
        mitchell_stub,
    )
    assert result.exit_code == 0, result.output
    dag = parse_dag((tmp_path / "dag" / "catalogue.dag").read_text())
    assert sorted(dag["vars"][n]["event"] for n in dag["vars"]) == sorted(
        stub_gwresults
    )
    assert dag["maxjobs"] == {"convert": condor.DEFAULT_MAX_DOWNLOADS}

    submit = parse_submit((tmp_path / "dag" / "convert_gwtc.sub").read_text())
    assert split_arguments(submit["arguments"]) == [
        "from-gwtc",
        "part.zarr",
        "--event",
        "$(event)",
    ]
    assert "transfer_input_files" not in submit  # nothing to send: it downloads


def test_gwtc_node_command_builds_a_single_event_store(
    tmp_path, mitchell_stub, stub_gwresults, monkeypatch
):
    """The node's command, run as written, produces a mergeable store."""
    monkeypatch.chdir(tmp_path)
    result = run("from-gwtc", "part.zarr", "--event", stub_gwresults[1])
    assert result.exit_code == 0, result.output
    out = MitchellStore.open(tmp_path / "catalogue.zarr")
    out.merge([tmp_path / "part.zarr"])
    assert [e.name for e in out] == [stub_gwresults[1]]


def test_gwtc_limit_and_event_filters(tmp_path, mitchell_stub, stub_gwresults):
    run(
        "condor-dag",
        tmp_path / "a",
        tmp_path / "c.zarr",
        "--gwtc",
        "--limit",
        "2",
        "--mitchell",
        mitchell_stub,
    )
    dag = parse_dag((tmp_path / "a" / "catalogue.dag").read_text())
    assert len(dag["jobs"]) == 3  # two conversions + combine

    run(
        "condor-dag",
        tmp_path / "b",
        tmp_path / "c.zarr",
        "--gwtc",
        "--event",
        stub_gwresults[2],
        "--mitchell",
        mitchell_stub,
    )
    dag = parse_dag((tmp_path / "b" / "catalogue.dag").read_text())
    assert [v["event"] for v in dag["vars"].values()] == [stub_gwresults[2]]


# -- options and errors ------------------------------------------------------


def test_options_reach_the_submit_files(tmp_path, h5_dir, mitchell_stub):
    dag_dir = generate(
        tmp_path,
        h5_dir,
        mitchell_stub,
        "--request-memory",
        "6GB",
        "--request-disk",
        "10GB",
        "--retries",
        "5",
        "--max-jobs",
        "4",
        "--accounting-group",
        "ligo.dev.o4.cbc",
        "--accounting-group-user",
        "albert.einstein",
        "--container-image",
        "/cvmfs/img.sif",
        "--keep-parts",
    )
    convert = parse_submit((dag_dir / "convert_h5.sub").read_text())
    combine = parse_submit((dag_dir / "combine.sub").read_text())
    assert convert["request_memory"] == "6GB"
    assert convert["request_disk"] == "10GB"
    assert convert["universe"] == "container"
    assert convert["container_image"] == "/cvmfs/img.sif"
    for sub in (convert, combine):
        assert sub["accounting_group"] == "ligo.dev.o4.cbc"
        assert sub["accounting_group_user"] == "albert.einstein"
    assert split_arguments(combine["arguments"])[-1] == "--copy"
    dag = parse_dag((dag_dir / "catalogue.dag").read_text())
    assert set(dag["retry"].values()) == {5}
    assert dag["maxjobs"] == {"convert": 4}


def test_no_throttle_by_default_for_local_files(tmp_path, h5_dir, mitchell_stub):
    dag_dir = generate(tmp_path, h5_dir, mitchell_stub)
    assert parse_dag((dag_dir / "catalogue.dag").read_text())["maxjobs"] == {}


def test_needs_exactly_one_source(tmp_path, h5_dir, mitchell_stub):
    neither = run(
        "condor-dag", tmp_path / "d", tmp_path / "c.zarr", "--mitchell", mitchell_stub
    )
    assert neither.exit_code != 0
    assert "exactly one" in neither.output
    both = run(
        "condor-dag", tmp_path / "d", tmp_path / "c.zarr",
        "--h5-dir", h5_dir, "--gwtc", "--mitchell", mitchell_stub,
    )  # fmt: skip
    assert both.exit_code != 0
    assert "exactly one" in both.output


def test_unnamed_files_are_reported_not_dropped(tmp_path, h5_dir, mitchell_stub):
    make_pesummary_h5(h5_dir / "mystery.h5")
    result = run(
        "condor-dag", tmp_path / "d", tmp_path / "c.zarr",
        "--h5-dir", h5_dir, "--mitchell", mitchell_stub,
    )  # fmt: skip
    assert result.exit_code != 0
    assert "mystery.h5" in result.output


def test_nothing_to_do_is_an_error(tmp_path, h5_dir, mitchell_stub):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run(
        "condor-dag", tmp_path / "d", tmp_path / "c.zarr",
        "--h5-dir", empty, "--mitchell", mitchell_stub,
    )  # fmt: skip
    assert result.exit_code != 0
    assert "No .h5 files" in result.output

    # Everything already built: a second DAG would do nothing.
    for path in sorted(h5_dir.glob("*.h5")):
        name = re.search(r"GW\d{6}_\d{6}", path.name).group()
        MitchellStore.from_pesummary_h5(path, name, tmp_path / "c.zarr")
    again = run(
        "condor-dag", tmp_path / "d2", tmp_path / "c.zarr",
        "--h5-dir", h5_dir, "--mitchell", mitchell_stub,
    )  # fmt: skip
    assert again.exit_code != 0
    assert "Nothing to do" in again.output


def test_missing_mitchell_executable_is_explained(tmp_path, h5_dir, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = run("condor-dag", tmp_path / "d", tmp_path / "c.zarr", "--h5-dir", h5_dir)
    assert result.exit_code != 0
    assert "--mitchell" in result.output


def test_paths_that_cannot_pass_through_a_dag_are_rejected(tmp_path, mitchell_stub):
    awkward = tmp_path / "h5"
    awkward.mkdir()
    make_pesummary_h5(awkward / 'GW000001_000000,"x".h5')
    result = run(
        "condor-dag", tmp_path / "d", tmp_path / "c.zarr",
        "--h5-dir", awkward, "--mitchell", mitchell_stub,
    )  # fmt: skip
    assert result.exit_code != 0
    assert "rename it" in result.output


def test_node_name_collisions_are_caught():
    nodes = [condor.Node("GW1.a"), condor.Node("GW1_a")]
    with pytest.raises(ValueError, match="same DAG node name"):
        condor.node_names(nodes)
