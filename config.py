"""
Central configuration. League URLs, name normalization maps, and file paths
all live here so the notebooks and pipeline stay in sync automatically.
"""

# ---------------------------------------------------------------------------
# League URLs by season year
# ---------------------------------------------------------------------------
# 2008 is absent (no league that year).
LEAGUE_URLS: dict[int, str] = {
    2007: "https://football.fantasysports.yahoo.com/2007/f1/580505",
    2009: "https://football.fantasysports.yahoo.com/2009/f1/790872",
    2010: "https://football.fantasysports.yahoo.com/2010/f1/438659",
    2011: "https://football.fantasysports.yahoo.com/2011/f1/211725",
    2012: "https://football.fantasysports.yahoo.com/2012/f1/324073",
    2013: "https://football.fantasysports.yahoo.com/2013/f1/378899",
    2014: "https://football.fantasysports.yahoo.com/2014/f1/329823",
    2015: "https://football.fantasysports.yahoo.com/2015/f1/216667",
    2016: "https://football.fantasysports.yahoo.com/2016/f1/370526",
    2017: "https://football.fantasysports.yahoo.com/2017/f1/347949",
    2018: "https://football.fantasysports.yahoo.com/2018/f1/153194",
    2019: "https://football.fantasysports.yahoo.com/2019/f1/102231",
    2020: "https://football.fantasysports.yahoo.com/2020/f1/523631",
    2021: "https://football.fantasysports.yahoo.com/2021/f1/696126",
    2022: "https://football.fantasysports.yahoo.com/2022/f1/709240",
    2023: "https://football.fantasysports.yahoo.com/2023/f1/199957",
    2024: "https://football.fantasysports.yahoo.com/2024/f1/710941",
}

SEASONS = sorted(LEAGUE_URLS.keys())

# FAAB was introduced in 2017. Prior seasons had straight waiver wire.
FAAB_START_YEAR = 2017

# ---------------------------------------------------------------------------
# Manager name normalization
# Draft sheets use short names; this maps them to the canonical full name.
# ---------------------------------------------------------------------------
MANAGER_NAME_MAP: dict[str, str] = {
    "Ben": "Benjamin",
    "David": "David Casstevens",
    "Scott": "Scott Gunter",
    "KJ": "Kevin",
    "Pat": "Patrick",
}

# ---------------------------------------------------------------------------
# Position aliases
# Draft sheets (and older scraped data) use various abbreviations for DEF.
# ---------------------------------------------------------------------------
POSITION_ALIASES: dict[str, str] = {
    "DST": "DEF",
    "D": "DEF",
    "Def": "DEF",
}

# ---------------------------------------------------------------------------
# Defense team → Yahoo player_id mapping
# Used to look up DEF entries that don't have a human player_id.
# ---------------------------------------------------------------------------
DEF_TEAM_IDS: dict[str, str] = {
    "arizona": "100022",
    "atlanta": "100001",
    "baltimore": "100033",
    "buffalo": "100002",
    "carolina": "100029",
    "chicago": "100003",
    "cincinnati": "100004",
    "cleveland": "100005",
    "dallas": "100006",
    "denver": "100007",
    "detroit": "100008",
    "green-bay": "100009",
    "houston": "100034",
    "indianapolis": "100011",
    "jacksonville": "100030",
    "kansas-city": "100012",
    "la-chargers": "100024",
    "la-rams": "100014",
    "st-louis": "5239",
    "las-vegas": "100013",
    "miami": "100015",
    "minnesota": "100016",
    "new-england": "100017",
    "new-orleans": "100018",
    "ny-jets": "100020",
    "philadelphia": "100021",
    "pittsburgh": "100023",
    "san-francisco": "100025",
    "seattle": "100026",
    "tampa-bay": "100027",
    "washington": "100028",
}

# Inverted: player_id → city slug (used when displaying DEF names)
DEF_ID_TO_TEAM = {v: k for k, v in DEF_TEAM_IDS.items()}

# ---------------------------------------------------------------------------
# Data directory layout
# ---------------------------------------------------------------------------
DATA_REF     = "data/reference"   # static inputs (checked into git)
DATA_RAW     = "data/raw"         # year-specific scraped intermediates (gitignored)
DATA_PROC    = "data/processed"   # compiled master files
DATA_ARCHIVE = "data/archive"     # superseded / date-stamped old files

# ---------------------------------------------------------------------------
# Canonical file paths
# All pipeline stages read and write through these names.
# Year-specific intermediates use {year} formatting.
# ---------------------------------------------------------------------------
LKUP_PLAYER_PATH         = f"{DATA_REF}/lkup_player.csv"
NAMES_DICT_PATH          = f"{DATA_REF}/names_dict.csv"
OVERRIDES_PATH           = f"{DATA_REF}/overrides.yaml"
DRAFT_RESULTS_DIR        = f"{DATA_REF}/draft_results"

LEAGUE_DF_PATH           = f"{DATA_PROC}/league_df_master.csv"
MANAGERS_DF_PATH         = f"{DATA_PROC}/managers_df_master.csv"
STANDINGS_PATH           = f"{DATA_PROC}/standings_master_latest.csv"
CONSOLIDATED_MASTER_PATH = f"{DATA_PROC}/consolidated_master.csv"
DRAFT_DF_PATH            = f"{DATA_PROC}/full_seasons_draft_df.csv"

# These filenames are parameterised by the latest year included in the file.
def rs_matchups_path(thru_year: int) -> str:
    return f"{DATA_PROC}/all_regular_season_thru_{thru_year}.csv"

def playoffs_path(thru_year: int) -> str:
    return f"{DATA_PROC}/all_playoffs_thru_{thru_year}.csv"

def position_ranks_path(thru_year: int) -> str:
    return f"{DATA_PROC}/position_ranks_thru_{thru_year}.csv"

def faab_path(thru_year: int) -> str:
    return f"{DATA_PROC}/faab_thru_{thru_year}.csv"

def year_rs_path(year: int) -> str:
    return f"{DATA_RAW}/{year}_pre_matchups.csv"

def year_playoffs_path(year: int) -> str:
    return f"{DATA_RAW}/{year}_pre_playoffs.csv"

def year_positions_path(year: int) -> str:
    return f"{DATA_RAW}/{year}_position_scores.csv"

def year_faab_path(year: int) -> str:
    return f"{DATA_RAW}/{year}_faab.csv"
