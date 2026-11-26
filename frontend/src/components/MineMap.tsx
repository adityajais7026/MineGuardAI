/**
 * Credential-free mine location map (Leaflet + OpenStreetMap tiles).
 *
 * Shows ONLY coordinates the database actually holds:
 *  - real coordinates render as markers;
 *  - records without coordinates appear in the "unmapped" list below the map
 *    (never plotted, never guessed);
 *  - no fake locations are ever generated; if tile fetch fails (no network)
 *    Leaflet shows an empty grid and the coordinate table remains usable.
 */
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

export interface MapPoint {
  id: string
  label: string
  latitude: number
  longitude: number
  kind?: 'mine' | 'inspection' | 'violation' | 'emergency' | 'geofence'
}

const KIND_COLORS: Record<string, string> = {
  mine: '#2563eb',
  inspection: '#059669',
  violation: '#dc2626',
  emergency: '#b91c1c',
  geofence: '#7c3aed',
}

export default function MineMap({ points, height = 320 }: { points: MapPoint[]; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const map = L.map(containerRef.current, { scrollWheelZoom: false }).setView([22.0, 79.0], 4)
    mapRef.current = map

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map)

    const valid = points.filter((p) => Number.isFinite(p.latitude) && Number.isFinite(p.longitude))
    if (valid.length > 0) {
      const bounds = L.latLngBounds(valid.map((p) => [p.latitude, p.longitude] as [number, number]))
      map.fitBounds(bounds.pad(0.35))
    }
    for (const p of valid) {
      const color = KIND_COLORS[p.kind ?? 'mine'] ?? '#2563eb'
      const marker = L.circleMarker([p.latitude, p.longitude], {
        radius: 7, color, fillColor: color, fillOpacity: 0.85, weight: 2,
      }).addTo(map)
      marker.bindPopup(`<strong>${p.label.replace(/[<>&]/g, '')}</strong><br/>${p.latitude.toFixed(5)}, ${p.longitude.toFixed(5)}`)
    }
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [points])

  const unmapped = points.filter((p) => !(Number.isFinite(p.latitude) && Number.isFinite(p.longitude)))

  return (
    <div>
      <div ref={containerRef} style={{ height, borderRadius: 8, border: '1px solid var(--border, #ddd)' }} />
      <p className="muted" style={{ marginTop: 4 }}>
        Map tiles: OpenStreetMap (no credentials required). Only coordinates stored in the database
        are plotted — nothing is estimated or invented.
      </p>
      {unmapped.length > 0 && (
        <p className="muted">{unmapped.length} record(s) without coordinates are listed in the table and NOT shown on the map (location unavailable).</p>
      )}
    </div>
  )
}
