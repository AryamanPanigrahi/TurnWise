# Decisions (ADRs)

One entry per decision. New dependencies need a one-line reason here.

## 001 — Project name: TurnWise
Replaces the working name "Daari". Trademark, Play Store and domain checks pending.

## 002 — Start with Valhalla for routing
Richer per-edge attributes (bridge, tunnel, layer, highway=service) than OSRM, which we need for flyover vs service-road detection. Revisit if speed becomes a problem.
