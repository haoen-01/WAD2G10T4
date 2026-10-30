# Location share: turning a position into an area name

- Date: 29 Oct 2026
- Branch: `research/location-area-name`, from `dev` at `b8bd073`
- Question: issue #19 / ADR 0011 (amended 29 Oct). How does a browser position become an area name
  such as "Near Toa Payoh Central" and a rough ~500 m circle on a map? Which public services fit,
  with their keys, terms and rate limits; whether the browser or the API should call them, given
  `CLAUDE.md` allows the browser only keyless, display-only calls in `services/publicApis.ts`; and
  how to coarsen a position to ~500 m before it is stored or shown.
- Sources: the providers' own documents, listed at the end. Where a primary source did not say
  something, this note says so rather than filling it in from blogs.

## Where this sits now

ADR 0011 was amended on 29 Oct: the family may see the senior's **walk** on a map (where she is,
the trail, a replay) behind her own switch, on a simulated route kept in the browser. It says issue
#19 "is no longer needed for the map itself. It only matters if an area name is shown beside the
walk." So this note answers two uses:

1. **A label beside the walk** ("Walking near Toa Payoh Central"), and
2. **A rough-area mode** (the original 26 Oct design): only "Near Toa Payoh Central" and a ~500 m
   circle, no exact point or trail, for a senior who wants to share less.

For the walk map with real positions, ADR 0011 already says the walk must move into the API first.

## Answer in one paragraph

Coarsen the position **on the senior's phone** to the centre of a ~500 m grid square, send only
that square to the API, and let **the API** name it by looking it up in **URA's Master Plan 2019
Subzone boundaries** (a free data.gov.sg file, kept in the repo). No key, no outside call when it
runs, and the name ("Toa Payoh Central") is an official subzone name. OneMap's reverse geocoding is
the fallback if a finer name is ever wanted. It needs a token, so it can only ever be called by the
API, never the browser. Draw the circle with radius 500 m around the square's centre, so the circle
always contains her real position without pointing at it.

## 1. The services that fit

| Service                                                                                  | What it gives                                                                                                                                                                  | Key?                                                                                                                                           | Terms                                                                                                                                                                                                                       | Rate limit                                                                                                                                                                                                            | Who may call it                            |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| **URA Master Plan 2019 Subzone Boundary (No Sea)**, GeoJSON on data.gov.sg (recommended) | Subzone polygons with `SUBZONE_N` (e.g. "TOA PAYOH CENTRAL") and planning area `PLN_AREA_N`                                                                                    | None (a file, downloaded once)                                                                                                                 | "Free forever for personal or commercial use, under the Open Data Licence"                                                                                                                                                  | None at run time                                                                                                                                                                                                      | **The API**, from a copy in the repo       |
| **OneMap reverse geocode** (SLA)                                                         | Nearest building, block, road and postcode to a point, within a buffer of 0 to 500 m                                                                                           | **Yes**: "Token is needed for all endpoints except basemaps and staticmap api"; an RS256 JWT, "Validity for 3 days", from a registered account | API Terms of Service: allowed "whether commercially or non-commercially"; credentials kept "secure and confidential"; no rights over "any personal data … included or exposed through the APIs"; the Agency may monitor use | **Not stated** in the sources reached: the workshop slide titled "CALL RATE LIMIT" shows no figure, and the terms only point to "published technical … specifications". Check the API docs page before relying on it. | **The API only** (it holds a secret token) |
| **OneMap basemap tiles** (for the circle's map)                                          | Raster map of Singapore, `https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png` (also `Default_HD`, other styles: Original, Grey, GreyLite, Night, LandLot), EPSG:3857 | **None** for basemaps (SLA slides)                                                                                                             | Map docs: "you MUST include the OneMap logo and attribution"; full site Terms restrict storing or redistributing content except as permitted                                                                                | Not stated                                                                                                                                                                                                            | Browser, but see §2                        |
| **OneMap nearby MRT / bus stop**                                                         | Nearest stations within 0 to 5000 m ("Near Toa Payoh MRT")                                                                                                                     | Yes (as reverse geocode)                                                                                                                       | As reverse geocode                                                                                                                                                                                                          | Not stated                                                                                                                                                                                                            | The API only                               |

The OneMap API documentation itself (`onemap.gov.sg/apidocs`) is a JavaScript app that could not be
read for this note, so the exact reverse-geocode URL and the rate limit are **to confirm** there.
The figures above come from SLA's own workshop slides (26 Aug 2025), the maps page and the two
terms pages.

## 2. Browser or API?

- **The browser** may only make keyless, display-only calls that send nothing about the senior
  (`CLAUDE.md`, `services/publicApis.ts`). A reverse-geocode request _is_ her position, and OneMap
  needs a token, so it can never be called from the browser. Putting the token in a `VITE_`
  variable would publish it to everyone.
- **The API** may call OneMap with the token in its server-side `.env`. That is a new outside call
  carrying (coarse) location data, so it needs a line in ADR 0011 and in `docs/data-and-privacy.md`
  before it is turned on. The **subzone file needs no outside call at all**, which is why it is the
  recommendation.
- **Map tiles are a grey area.** They are keyless and display-only, but loading the tiles around her
  area tells the tile server which ~500 m square is being viewed. The walk map already does the same
  with OpenFreeMap tiles (`apps/web/src/lib/map-style.ts`) on a made-up route. Before real positions
  are shown, the team should record one of these in ADR 0011:
  - (a) accept that tile requests reveal the viewed area, at the coarse level only;
  - (b) serve tiles through the API; or
  - (c) show the rough-area mode as words only, with no map.

## 3. Coarsening to ~500 m

**Where:** on the senior's phone, before anything is sent, so the exact position never leaves it.
The API repeats the same step on whatever it receives, because a modified page could send exact
coordinates.

**How:** snap to a fixed grid and keep only the square's centre.

```text
STEP = 0.0045 degrees      (latitude: 0.0045 × 111.2 km ≈ 500 m;
                             longitude at 1.35° N: 0.0045 × 111.3 km × cos 1.35° ≈ 500 m)
cell_lat = (floor(lat / STEP) + 0.5) × STEP
cell_lng = (floor(lng / STEP) + 0.5) × STEP
```

- **Store** only `cell_lat`, `cell_lng`, the area name and the time; never the raw position.
- **Show** a circle of radius **500 m** around the cell centre. A point in a 500 m square is at most
  √(250² + 250²) ≈ 354 m from its centre, so the circle always contains her, and its centre is the
  square's centre, not her.
- **Name** the area from the cell centre (point-in-polygon against the subzones), not from the raw
  position, so the name gives away no more than the square. A cell centre that falls in the sea or
  outside every subzone gets the nearest subzone's name, or just "In Singapore".
- **Known limit:** a senior who stays near a square's edge can flip between two squares, which shows
  roughly where the edge is. Acceptable for ~500 m. If the team wants less, shift the grid origin by
  a fixed random offset per senior, kept server-side.

**Words on screen:** `"Near " + title_case(SUBZONE_N)`, e.g. "Near Toa Payoh Central", with the
time it was shared ("as of 4:12 pm"). Nothing on the screen implies an exact place or a safety
service (ADR 0011).

## 4. How it would flow

1. The senior has turned sharing on (ADR 0011). Her phone asks the browser for a position
   (`navigator.geolocation`; HTTPS only; the browser asks her permission).
2. Her phone coarsens it (§3) and sends only the cell through `services/careApi.ts`.
3. The API coarsens again, names the cell from the subzone file, and stores cell, name and time.
   FastAPI owns this write, as ADR 0011 requires before real positions are used.
4. The family's screen reads "Near Toa Payoh Central · as of 4:12 pm" and, if the team chose map
   option (a), a 500 m circle on the map.

## 5. What it would take to build (for whoever picks it up)

- Download the subzone GeoJSON (about 3 MB) once and commit a simplified copy under
  `apps/api/src/silverloop/data/` (rounding coordinates to 5 decimal places makes it much smaller),
  with a note of its source and licence.
- A pure point-in-polygon function in Python (ray casting; no new dependency), with a unit test on
  a few known points (for example Toa Payoh Central, a point in the sea, a point on a boundary).
- A coarsening function, mirrored in TypeScript for the phone, with tests that a coarsened point
  never moves more than about 354 m and that coarsening twice changes nothing.

## Open questions for the team

1. Is the label beside the walk wanted at all, or only the rough-area mode? (ADR 0011 says #19
   only matters for a label.)
2. Map tiles for real positions: option (a), (b) or (c) in §2?
3. If OneMap is ever used: someone registers a team account, and the API needs a job to renew the
   3-day token.

## Sources

- ADR 0011 `docs/adr/0011-location-share-is-not-a-safety-service.md`; `CLAUDE.md` (browser-call
  rule); `apps/web/src/lib/map-style.ts`.
- URA via data.gov.sg, [Master Plan 2019 Subzone Boundary (No Sea) (GEOJSON)](https://data.gov.sg/datasets/d_8594ae9ff96d0c708bc2af633048edfb/view)
  (fields `SUBZONE_N`, `PLN_AREA_N`; Open Data Licence; data from Sep 2021, page updated 3 Dec 2025).
- SLA, [OneMap API Workshop slides, 26 Aug 2025](https://www.onemap.gov.sg/apidocs/static/media/OneMap_API_Workshop_Demo_260825.6522ddef4affd370a81a.pdf)
  (token rules, reverse-geocode parameters, basemap styles).
- SLA, [OneMap maps documentation](https://www.onemap.gov.sg/docs/maps/) (tile URLs, attribution
  requirement).
- SLA, [OneMap API Terms of Service](https://www.onemap.gov.sg/legal/apitermsofservice.html) and
  [OneMap Terms of Use](https://www.onemap.gov.sg/legal/termsofuse.html).
