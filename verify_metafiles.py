import argparse
from contextlib import ContextDecorator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Set


class MsgStatus(str, Enum):
    normal = "normal"
    warning = "warning"
    failure = "failure"
    error = "error"


@dataclass
class TeamCityMsg:
    text: str
    properties: Dict[str, str]

    @property
    def _msg(self) -> str:
        props = list(f"{key}='{value}'" for key, value in self.properties.items())
        content = " ".join(
            [
                self.text,
            ]
            + props
        )
        return f"##teamcity[{content}]"

    def publish(self):
        print(self._msg)


@dataclass
class TestSuite(ContextDecorator):
    name: str

    def __enter__(self):
        msg = TeamCityMsg(text="testSuiteStarted", properties={"name": self.name})
        msg.publish()
        return self

    def __exit__(self, *exc):
        msg = TeamCityMsg(text="testSuiteFinished", properties={"name": self.name})
        msg.publish()
        return None


@dataclass
class Test(ContextDecorator):
    name: str

    _start_time: datetime = datetime.now()

    def __enter__(self):
        props = {
            "name": self.name,
            "captureStandardOutput": "false",
        }
        msg = TeamCityMsg(text="testStarted", properties=props)
        msg.publish()
        return self

    def __exit__(self, *exc):
        props = {
            "name": self.name,
            "duration": str(
                (datetime.now() - self._start_time) / timedelta(milliseconds=1)
            ),
        }

        msg = TeamCityMsg(text="testFinished", properties=props)
        msg.publish()
        return None

    def fail(self, message: str, details: str) -> None:
        props = {
            "name": self.name,
            "message": message,
            "details": details,
        }
        msg = TeamCityMsg(text="testFailed", properties=props)
        msg.publish()

    def ignore(self, comment: str) -> None:
        props = {"name": self.name, "message": comment}
        msg = TeamCityMsg(text="testIgnored", properties=props)
        msg.publish()


def _find_elems(
    root: Path,
    is_excluded_transverse: Callable[[Path], bool],
    is_excluded_result: Optional[Callable[[Path], bool]] = None,
) -> Set[Path]:
    if is_excluded_result is None:
        is_excluded_result_ = lambda _: False
    else:
        is_excluded_result_ = is_excluded_result

    def _find_elems_rec(p: Path, acc: Set[Path]) -> Set[Path]:
        paths = [pc for pc in p.iterdir() if not is_excluded_transverse(pc)]
        acc = acc.union(pc for pc in paths if not is_excluded_result_(pc))

        for p in paths:
            if p.is_dir():
                acc = _find_elems_rec(p, acc)
        return acc

    return _find_elems_rec(root, set())


def gather_metafile_paths(root: Path, excluded_dirs: Set[str]) -> Set[Path]:
    def _is_excluded(p: Path) -> bool:
        if p.is_file():
            return p.suffix != ".meta"
        return p.name in excluded_dirs

    def _is_not_metafile(p: Path) -> bool:
        return p.is_dir()

    return _find_elems(root, _is_excluded, _is_not_metafile)


def gather_asset_paths(
    root: Path, excluded_files: Set[str], excluded_directories: Set[str]
) -> Set[Path]:
    def _is_excluded(p: Path) -> bool:
        filter = excluded_directories if p.is_dir() else excluded_files
        return p.name in filter or p.suffix == ".meta"

    return _find_elems(root, _is_excluded)


def is_dangling_metafile(metafile: Path, assets: Set[Path]) -> bool:
    return metafile.with_suffix("") not in assets


def is_missing_metafile(asset: Path, metafiles: Set[Path]) -> bool:
    return asset.with_suffix(asset.suffix + ".meta") not in metafiles


@TestSuite(name="missing_metafiles")
def verify_missing_metafiles(assets: Set[Path], metafiles: Set[Path]):
    for asset_path in assets:
        with Test(name=str(asset_path)) as test:
            if is_missing_metafile(asset_path, metafiles):
                test.fail("No .metafile", f"Metafile {asset_path}.meta not found.")


@TestSuite(name="dangling_metafiles")
def verify_dangling_metafiles(assets: Set[Path], metafiles: Set[Path]):
    for metafile_path in metafiles:
        with Test(name=str(metafile_path)) as test:
            if is_dangling_metafile(metafile_path, assets):
                test.fail("No asset", f"No file corresponding with {metafile_path}.")


def _retrieve_excluded_args(elems: Optional[Sequence[str]]) -> Set[str]:
    return set(elems) if elems is not None else set()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify no missing or dangling .metafiles."
    )
    parser.add_argument("root", type=str)
    parser.add_argument("--exclude_file", "-ef", dest="excluded_files", action="append")
    parser.add_argument("--exclude_dir", "-ed", dest="excluded_dirs", action="append")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    root = Path(args.root)

    excluded_files = _retrieve_excluded_args(args.excluded_files)
    excluded_dirs = _retrieve_excluded_args(args.excluded_dirs)

    assets = gather_asset_paths(root, excluded_files, excluded_dirs)
    metafiles = gather_metafile_paths(root, excluded_dirs)

    verify_missing_metafiles(assets, metafiles)
    verify_dangling_metafiles(assets, metafiles)
