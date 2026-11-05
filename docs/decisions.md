# Decisions (ADRs)

One entry per decision. New dependencies need a one-line reason here.

## 001 — Project name: TurnWise
Replaces the working name "Daari". Trademark, Play Store and domain checks pending.

## 002 — Start with Valhalla for routing
Richer per-edge attributes (bridge, tunnel, layer, highway=service) than OSRM, which we need for flyover vs service-road detection. Revisit if speed becomes a problem.

## 003 — Geocoding: free OSM-based now, paid provider once fleets pay
Valhalla only takes coordinates, so stop addresses must be geocoded server-side in `backend/` when a stop is created, then stored as lat/lon. Dispatchers confirm the resolved pin on the dashboard map before the trip starts.
- **Now:** self-hosted Nominatim or Photon on the same OSM data (free, ODbL-compatible).
- **Later (paying fleets):** switch to MapmyIndia/Mappls for better Indian address coverage. Before switching, read their terms on storing geocoded results and on mixing their data with OSM-derived data (rule 6).
- **Design rule:** the backend calls geocoding through one small interface (`geocode(text) -> candidates`), so changing provider touches one module.
- **Risk:** OSM address coverage in India is patchy; include geocoding quality in the OSM coverage audit of pilot routes.
