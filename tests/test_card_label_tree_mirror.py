"""The events card's label-tree helpers must agree with the main app's.

`labelTreeItems` / `expandWithDescendants` in `purrview-events-card.js` are hand-copies
of `labelFacetItems` (the app's `nvr/events/filters.js`) and `expandWithDescendants`
(its `ui/labelList.js`). They live in two different repos with no build step shared
between them, so nothing stops one side from being improved and the other left behind -
and the symptom is not a crash but a Subject filter that quietly means something
different in Home Assistant than it does in the app.

So this asserts the two sides *equal each other* over one tree, rather than pinning
either to a literal. It needs the sibling app checkout and node, and skips when either
is absent - a HACS user who cloned only this repo has neither.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HARNESS = _REPO / "tests" / "js" / "label_tree_mirror.mjs"

#: Overridable because the app checkout is only conventionally the sibling directory;
#: it is still named `whiskerwatcher` on disk even though the project is PurrView.
_APP_REPO = Path(__file__).resolve().parents[2] / "whiskerwatcher"

_node = shutil.which("node")

pytestmark = [
    pytest.mark.skipif(_node is None, reason="node is not installed"),
    pytest.mark.skipif(not _APP_REPO.is_dir(), reason=f"no app checkout at {_APP_REPO}"),
]


@pytest.fixture(scope="module")
def mirror():
    result = subprocess.run(
        [_node, str(_HARNESS), str(_REPO), str(_APP_REPO)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_card_builds_the_same_tree_as_the_app(mirror):
    assert mirror["cardTree"] == mirror["appTree"]


def test_the_card_rolls_a_parent_up_to_the_same_descendants(mirror):
    assert mirror["cardExpand"] == mirror["appExpand"]


def test_the_tree_is_not_merely_the_flat_facet_list(mirror):
    """Guards the comparison itself. Two implementations that both returned the input
    unchanged would agree perfectly and prove nothing, so check the shared result
    actually synthesises the ancestors and separates the non-label refs."""
    tree = mirror["cardTree"]
    assert any(row.get("depth") for row in tree), "nothing was nested"
    assert any(row.get("ref") == "veh" for row in tree), "an ancestor with no events of its own was dropped"
    assert any(row.get("separator") for row in tree), "the non-label zone ref was not separated"
