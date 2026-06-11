"""Dashboard-wide constants: route exclusions, event dates, region groupings."""

# 12940/6700/30055/6702/6718 — stop-sequence tie artifacts (LAG corruption)
# 6619 — structural GTFS join failure: Lougheed Hwy extension + termini have
#         no shape_dist_traveled in gtfs_static.db; NULL pattern is geographic,
#         not random — remaining sample is biased to central Broadway corridor
ANOMALY_ROUTES = ["12940", "6700", "30055", "6702", "6718", "6619"]
HOLDOUT_ROUTES = ["6641", "6705"]
FIFA_MATCH_DATES = [
    "2026-06-13", "2026-06-18", "2026-06-21",
    "2026-06-24", "2026-06-26", "2026-07-02", "2026-07-07",
]
DATA_START = "2026-05-23"
DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# BC Data Catalogue WFS — official provincial government source
MV_WFS_URL = (
    "https://openmaps.gov.bc.ca/geo/pub/wfs"
    "?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&typeName=WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP"
    "&outputFormat=application/json"
    "&CQL_FILTER=ADMIN_AREA_GROUP_NAME%3D%27Metro+Vancouver+Regional+District%27"
    "&srsName=EPSG:4326"
)

# Broader region groupings (municipality → region label)
REGION_GROUPS = {
    "City of Vancouver":                              "Vancouver",
    "City of Burnaby":                                "Burnaby / New West",
    "City of New Westminster":                        "Burnaby / New West",
    "City of Richmond":                               "Richmond / Delta",
    "City of Delta":                                  "Richmond / Delta",
    "City of Surrey":                                 "Surrey / Langley",
    "City of Langley":                                "Surrey / Langley",
    "The Corporation of the Township of Langley":     "Surrey / Langley",
    "City of White Rock":                             "Surrey / Langley",
    "City of Coquitlam":                              "Tri-Cities",
    "City of Port Coquitlam":                         "Tri-Cities",
    "City of Port Moody":                             "Tri-Cities",
    "Village of Anmore":                              "Tri-Cities",
    "Village of Belcarra":                            "Tri-Cities",
    "City of North Vancouver":                        "North Shore",
    "The Corporation of the District of North Vancouver": "North Shore",
    "District Municipality of West Vancouver":        "North Shore",
    "Bowen Island Municipality":                      "North Shore",
    "Village of Lions Bay":                           "North Shore",
    "City of Maple Ridge":                            "East Valley",
    "City of Pitt Meadows":                           "East Valley",
}

ANOMALY_EXCL = "','".join(ANOMALY_ROUTES)
