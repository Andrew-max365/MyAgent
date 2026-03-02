# tests/test_react_schemas.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.graph.react_schemas import Action, ActionPlan, Observation, GraphState


def test_action_valid():
    a = Action(action_type="set_role", block_id=0, params={"role": "h1"})
    assert a.action_type == "set_role"
    assert a.block_id == 0
    assert a.params == {"role": "h1"}


def test_action_no_op():
    a = Action(action_type="no_op", block_id=-1)
    assert a.action_type == "no_op"
    assert a.params == {}


def test_action_invalid_type():
    with pytest.raises(ValidationError):
        Action(action_type="invalid_action", block_id=0)


def test_action_plan():
    plan = ActionPlan(
        thought="test thought",
        actions=[Action(action_type="no_op", block_id=-1)],
        rationale="test rationale",
    )
    assert plan.thought == "test thought"
    assert len(plan.actions) == 1
    assert plan.rationale == "test rationale"


def test_action_plan_dump():
    plan = ActionPlan(
        thought="t",
        actions=[Action(action_type="fix_heading_level", block_id=2, params={"level": 2})],
        rationale="r",
    )
    dumped = plan.model_dump()
    assert dumped["actions"][0]["action_type"] == "fix_heading_level"
    assert dumped["actions"][0]["params"] == {"level": 2}


def test_observation_defaults():
    obs = Observation(iteration=1, passed=True)
    assert obs.errors == []
    assert obs.applied_actions == []
    assert obs.summary == ""


def test_observation_with_errors():
    obs = Observation(iteration=2, passed=False, errors=["some error"], summary="failed")
    assert obs.passed is False
    assert obs.errors == ["some error"]


def test_graph_state_is_typed_dict():
    # GraphState is a TypedDict — just verify the expected keys exist in annotations
    keys = GraphState.__annotations__.keys()
    for key in (
        "input_path", "output_path", "spec_path", "label_mode",
        "max_iters", "current_iter", "thoughts", "actions",
        "observations", "errors", "passed", "finished", "report",
        "blocks", "labels", "doc",
    ):
        assert key in keys, f"Missing key: {key}"


def test_all_action_types():
    valid_types = ["set_role", "fix_heading_level", "normalize_list", "adjust_paragraph_style", "no_op"]
    for at in valid_types:
        a = Action(action_type=at, block_id=0)
        assert a.action_type == at
