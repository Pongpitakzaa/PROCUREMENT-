from app.core.security import generate_temp_password, password_problems, role_combination_problems


def test_password_policy():
    assert password_problems("short1") and password_problems("onlyletterslong")
    assert password_problems("officer2026abc", "officer") == ["ห้ามมีชื่อผู้ใช้อยู่ในรหัสผ่าน"]
    assert password_problems("Correct-Horse-42") == []


def test_temp_password_meets_policy_and_is_random():
    pws = {generate_temp_password() for _ in range(50)}
    assert len(pws) == 50 and all(len(p) == 16 and not password_problems(p) for p in pws)
    assert not any(c in "0O1lI" for p in pws for c in p)        # ไม่มีตัวที่สับสนง่าย


def test_role_segregation_of_duties():
    assert role_combination_problems({"PROCUREMENT_OFFICER"}) == []
    assert role_combination_problems({"HEAD_OF_PROCUREMENT", "EXECUTIVE"}) == []
    assert role_combination_problems({"ADMIN", "HEAD_OF_PROCUREMENT"})          # admin ห้ามทำงานพัสดุ
    assert role_combination_problems({"AUDITOR", "EXECUTIVE"})                  # auditor ต้องอิสระ
    assert role_combination_problems(set())
    assert role_combination_problems({"ROOT"})


def test_full_name_spacing_for_rank_abbreviations():
    """คำย่อยศ (พ.อ.อ., น.อ.) เว้นวรรคก่อนชื่อ · นาย/นาง/นางสาว ไม่เว้น."""
    from app.models import Personnel
    assert Personnel(title_th="นาย", first_name_th="สมชาย", last_name_th="ใจดี").full_name_th == "นายสมชาย ใจดี"
    assert Personnel(title_th="พ.อ.อ.", first_name_th="สมชาย", last_name_th="ใจดี").full_name_th == "พ.อ.อ. สมชาย ใจดี"
    assert Personnel(title_th="น.อ.", first_name_th="สมหญิง", last_name_th="รักงาน").full_name_th == "น.อ. สมหญิง รักงาน"
