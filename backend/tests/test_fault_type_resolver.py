from app.services.fault_type_resolver import resolve_fault_type


def test_resolve_fault_type_from_incident_title() -> None:
    assert resolve_fault_type("无人机巡检: YJ-A-013 叶片前缘侵蚀") == "叶片前缘侵蚀"
    assert resolve_fault_type("Demo: gearbox_tooth_pitting alarm") == "齿轮箱点蚀"


def test_resolve_fault_type_keeps_unknown_label() -> None:
    assert resolve_fault_type("未知异常") == "未知异常"
    assert resolve_fault_type(None) is None
