from edgar13f import parse

COVER = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
 <headerData><filerInfo><periodOfReport>12-31-2024</periodOfReport></filerInfo></headerData>
 <formData><coverPage>
  <reportCalendarOrQuarter>12-31-2024</reportCalendarOrQuarter>
  <isAmendment>true</isAmendment><amendmentNo>2</amendmentNo>
  <amendmentInfo><amendmentType>RESTATEMENT</amendmentType></amendmentInfo>
  <filingManager><name>Example Manager LLC</name></filingManager>
  <reportType>13F HOLDINGS REPORT</reportType>
 </coverPage></formData>
</edgarSubmission>"""

TABLE = b"""<?xml version="1.0"?>
<ns1:informationTable xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf/informationtable">
 <ns1:infoTable>
  <ns1:nameOfIssuer>EXAMPLE CORP</ns1:nameOfIssuer><ns1:titleOfClass>COM</ns1:titleOfClass>
  <ns1:cusip>12345a789</ns1:cusip><ns1:figi>BBG000000001</ns1:figi><ns1:value>1234567</ns1:value>
  <ns1:shrsOrPrnAmt><ns1:sshPrnamt>100</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>
  <ns1:putCall>Call</ns1:putCall><ns1:investmentDiscretion>DFND</ns1:investmentDiscretion>
  <ns1:otherManager>1,2</ns1:otherManager>
  <ns1:votingAuthority><ns1:Sole>10</ns1:Sole><ns1:Shared>20</ns1:Shared><ns1:None>70</ns1:None></ns1:votingAuthority>
 </ns1:infoTable>
 <ns1:infoTable>
  <ns1:nameOfIssuer>EXAMPLE CORP</ns1:nameOfIssuer><ns1:titleOfClass>COM</ns1:titleOfClass>
  <ns1:cusip>12345A789</ns1:cusip><ns1:value>5</ns1:value>
  <ns1:shrsOrPrnAmt><ns1:sshPrnamt>1</ns1:sshPrnamt><ns1:sshPrnamtType>PRN</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>
  <ns1:investmentDiscretion>SOLE</ns1:investmentDiscretion>
  <ns1:votingAuthority><ns1:Sole>0</ns1:Sole><ns1:Shared>0</ns1:Shared><ns1:None>0</ns1:None></ns1:votingAuthority>
 </ns1:infoTable>
</ns1:informationTable>"""


def test_cover():
    assert parse.parse_cover(COVER) == {
        "period_of_report": "2024-12-31", "amendment_no": 2, "amendment_type": "RESTATEMENT",
        "report_type": "13F HOLDINGS REPORT", "filing_manager_name": "Example Manager LLC",
    }


def test_infotable_rows_as_filed_not_merged():
    assert parse.is_infotable(TABLE) and not parse.is_infotable(COVER)
    rows = parse.parse_infotable(TABLE, "0000000001-25-000001")
    assert len(rows) == 2
    a, b = rows
    assert a == {
        "accession_number": "0000000001-25-000001", "name_of_issuer": "EXAMPLE CORP", "title_of_class": "COM",
        "cusip": "12345a789", "figi": "BBG000000001", "value": 1234567, "shares_or_principal_amount": 100,
        "sh_prn": "SH", "put_call": "CALL", "investment_discretion": "DFND", "other_manager": "1,2",
        "voting_authority_sole": 10, "voting_authority_shared": 20, "voting_authority_none": 70,
    }
    assert b["put_call"] is None and b["figi"] is None and b["other_manager"] is None and b["sh_prn"] == "PRN"


def test_dates():
    assert parse.mdy_to_iso("3-31-2025") == "2025-03-31"
    assert parse.mdy_to_iso("2025-03-31") == "2025-03-31"
    assert parse.mdy_to_iso("garbage") is None and parse.mdy_to_iso(None) is None
