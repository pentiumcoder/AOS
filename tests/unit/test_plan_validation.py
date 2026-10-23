from aos.schemas import ExecutionPlan, Subtask, ready_subtasks, validate_plan


def make_plan(*subtasks: Subtask, confidence: float = 0.8) -> ExecutionPlan:
    return ExecutionPlan(
        task_type="test", rationale="test", confidence=confidence, subtasks=list(subtasks)
    )


def step(sid: str, specialist: str = "research", deps: list[str] | None = None) -> Subtask:
    return Subtask(
        id=sid,
        description=f"do {sid}",
        specialist=specialist,
        depends_on=deps or [],
        expected_output="text",
    )


def test_valid_plan_has_no_errors():
    plan = make_plan(step("s1"), step("s2", "data_analysis"), step("s3", "writing", ["s1", "s2"]))
    assert validate_plan(plan) == []


def test_cycle_is_reported_with_path():
    plan = make_plan(step("s1", deps=["s3"]), step("s2", deps=["s1"]), step("s3", deps=["s2"]))
    errors = validate_plan(plan)
    assert len(errors) == 1
    assert errors[0].startswith("plan has cycle: ")
    assert {"s1", "s2", "s3"} <= set(errors[0].replace("plan has cycle: ", "").split(" -> "))


def test_unknown_specialist_and_missing_dependency():
    plan = make_plan(step("s1", "astrologer"), step("s2", deps=["s9"]))
    errors = validate_plan(plan)
    assert "s1 uses unknown specialist astrologer" in errors
    assert "s2 depends on unknown subtask s9" in errors


def test_duplicate_ids_self_dependency_and_size_limit():
    assert validate_plan(make_plan(step("s1"), step("s1"))) == ["duplicate subtask ids: s1"]
    assert validate_plan(make_plan(step("s1", deps=["s1"]))) == ["s1 depends on itself"]
    too_many = make_plan(*(step(f"s{i}") for i in range(13)))
    assert any("limit is 12" in e for e in validate_plan(too_many))
    assert validate_plan(make_plan()) == ["plan has no subtasks"]


def test_ready_subtasks_waits_for_dependencies():
    plan = make_plan(step("s1"), step("s2"), step("s3", "writing", ["s1", "s2"]))
    assert [s.id for s in ready_subtasks(plan, {})] == ["s1", "s2"]
    assert ready_subtasks(plan, {"s1": "done", "s2": "running", "s3": "pending"}) == []
    status = {"s1": "done", "s2": "done", "s3": "needs_revision"}
    assert [s.id for s in ready_subtasks(plan, status)] == ["s3"]


def test_dependencies_named_in_description_or_inputs_are_added():
    from aos.schemas.plan import infer_dependencies

    s3 = step("s3", "data_analysis")
    s3.description = "Pick the fastest database from the results of s1"
    s4 = step("s4", "writing", ["s3"])
    s4.inputs = {"costs": "subtask:s2"}
    plan = infer_dependencies(make_plan(step("s1"), step("s2"), s3, s4))
    assert plan.subtask("s3").depends_on == ["s1"]
    assert plan.subtask("s4").depends_on == ["s3", "s2"]
    assert plan.subtask("s1").depends_on == []
