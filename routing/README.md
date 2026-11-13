# routing/ — Valhalla on a Bengaluru extract

Valhalla builds *tiles* (a graph of road edges with attributes such as
bridge, tunnel, layer, highway=service) from an OpenStreetMap `.pbf` file,
then serves routing and map-matching over HTTP on port 8002.
Map data: © OpenStreetMap contributors (ODbL).

All commands below are PowerShell (Windows). Run from the repo root.

## One-time setup

1. Download the India southern-zone extract (Geofabrik has no Karnataka-only file):
   ```powershell
   New-Item -ItemType Directory -Force routing/data-archive
   curl.exe -L -o routing/data-archive/southern-zone-latest.osm.pbf https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf
   ```
   Use `curl.exe`, not `curl` (PowerShell aliases `curl` to Invoke-WebRequest).

2. Clip it to Bengaluru with osmium (run via Docker, nothing to install).
   Box: west 77.35, south 12.75, east 77.90, north 13.25.
   ```powershell
   New-Item -ItemType Directory -Force routing/data
   docker run --rm -v "${PWD}/routing/data-archive:/in" -v "${PWD}/routing/data:/out" iboates/osmium extract --bbox 77.35,12.75,77.90,13.25 /in/southern-zone-latest.osm.pbf -o /out/bengaluru.osm.pbf
   ```
   Expect ~45 MB. Routes leaving this box will fail; use a bigger box for pilots outside the city.

3. Build tiles and start the server (first start builds tiles, ~10 min):
   ```powershell
   docker run -d --name valhalla -p 8002:8002 -v "${PWD}/routing/data:/custom_files" ghcr.io/gis-ops/docker-valhalla/valhalla:latest
   docker logs -f valhalla
   ```
   Keep exactly one `.pbf` in `routing/data/`. Tiles are saved there and reused on later starts.

## Day to day

```powershell
docker start valhalla
docker stop valhalla
```

## Smoke test (MG Road to Electronic City, expect ~17.9 km, ~22 min)

```powershell
(Invoke-RestMethod -Method Post -Uri http://localhost:8002/route -Body '{"locations":[{"lat":12.9757,"lon":77.6061},{"lat":12.8456,"lon":77.6603}],"costing":"auto"}').trip.summary
```

## Problems we hit

- **Full southern-zone build crashed** ("EdgeInfo offsets incorrect when reading GraphTile"), probably a Valhalla bug on that large file. The clipped Bengaluru file builds fine.
- **Tiny `.pbf` (a few KB)** means the download was an HTML error page, not map data. Check the size before building. (The BBBike city URL we tried did not work.)
- **Harmless warnings:** `Invalid level`, `Admin db` / `Time zone db not found`, `traffic.tar`, `Exceeding max. density`.
