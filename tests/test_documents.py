import pytest

from vsia import documents as d

OLD_573 = """<!-- page 1 -->
Part 573 Safety Recall Report         24V-051
Vehicle Information :
Vehicle  1 : 2017-2025 Tesla Model 3
Vehicle  2 : 2024-2024 Tesla Cybertruck
Description of Noncompliance :
Description of the
Noncompliance :
On affected vehicles, the letter font size of the Brake warning indicator is too small.
FMVSS 1 : 105 - Hydraulic and electric brake systems

<!-- page 2 -->
Page 2Part 573 Safety Recall Report         24V-051
Description of the Safety Risk : Reduced detection of the indicator.
Description of Remedy :
Description of Remedy Program : An over-the-air software remedy increases the font size.
How Remedy Component Differs
from Recalled Component :
Newer software.
"""

NEW_573 = """<!-- page 5 -->
Defect / Noncompliance Description
Description of the defect or noncompliance:
On affected vehicles, the rearview camera image may not display.
Description of the safety risk:
Reduced rear visibility.
Description of Remedy
Description of remedy program:
Dealers will update the software free of charge.
Identify how/when recall condition was corrected in production:
Software updated.
"""

LETTER = """What is the issue? The front subframe bolts may not be tightened.
What is the risk? Loose bolts may affect crash performance.
What will Ford and your dealer do? Your dealer will tighten the bolts free of charge.
How long will it take? Less than half a day.
"""


def test_old_part573_layout():
    x = d.extract_rules(OLD_573, doc_type="RCLRPT", campaign_number="24V051000", component="ELECTRICAL SYSTEM",
                        make="TESLA", source_url=None)
    assert "font size" in x.defect_summary and "FMVSS" not in x.defect_summary
    assert x.remedy.startswith("An over-the-air software remedy")
    assert x.affected_models == ["Model 3", "Cybertruck"]
    assert x.model_years[0] == 2017 and x.model_years[-1] == 2025


def test_new_part573_layout():
    x = d.extract_rules(NEW_573, doc_type="RCLRPT", campaign_number="26V283000", component="BACK OVER PREVENTION",
                        make="FORD", source_url=None)
    assert x.defect_summary == "On affected vehicles, the rearview camera image may not display."
    assert x.remedy == "Dealers will update the software free of charge."


def test_owner_letter_layout():
    x = d.extract_rules(LETTER, doc_type="RCONL", campaign_number="21V140000", component="SUSPENSION",
                        make="FORD", source_url=None)
    assert "subframe bolts" in x.defect_summary and "crash performance" in x.defect_summary
    assert "tighten the bolts" in x.remedy


def test_missing_sections_raise():
    with pytest.raises(ValueError):
        d.extract_rules("nothing useful here", doc_type="RCLRPT", campaign_number="24V051000", component=None,
                        make=None, source_url=None)


def test_nr_section_is_treated_as_missing():
    text = "Description of the Defect :\nNR\nDescription of the Safety Risk : x\n"
    assert d._section(d._plain(text), d._DEFECT_LABEL, d._DEFECT_END) == ""
