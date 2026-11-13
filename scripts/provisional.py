"""
provisional.py - the ONE list of elections whose results are provisional.

An election is provisional while the report in source_pdfs/ is not confirmed to be the
county's certified canvass. Every output that carries a `provisional` flag (the workbook,
data/normalized/, site/data/) reads this list, so they can never disagree.

To finalize an election: replace its PDF in source_pdfs/ with the Clerk's certified report,
remove it from this list, rerun the pipeline, and note it in the release notes.
"""

PROVISIONAL = {
    "2026-PRIMARY": "report printed 5/12/2026, before the certification deadline; "
                    "not confirmed as the certified canvass",
    "2026-GENERAL": "election-night report (printed 11/3/2026 11:40 PM); "
                    "provisional until the county certifies",
}


def is_provisional(election):
    """election like '2026-GENERAL' (a source_file_id's -PRECINCT suffix is ignored)."""
    return election.replace("-PRECINCT", "") in PROVISIONAL
