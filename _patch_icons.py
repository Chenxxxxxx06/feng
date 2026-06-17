with open('frontend/src/components/Map/DroneMap.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# ── 1. Replace turbine marker ──
old_turbine_marker = "    farmItems.forEach((t) => {"
idx = content.index(old_turbine_marker)
# Find end of this forEach block
brace_count = 0
found = False
end_idx = idx
for i in range(idx, len(content)):
    if content[i] == '{':
        brace_count += 1
    elif content[i] == '}':
        brace_count -= 1
        if brace_count == 0 and i > idx + 10:
            # Check if next line is the useEffect closing
            rest = content[i+1:i+50].strip()
            if rest.startswith('}, [activeFarm') or not rest:
                end_idx = i + 1
                break

old_block = content[idx:end_idx]

new_block = """    farmItems.forEach((t) => {
      const shot = completedIds.has(t.id);
      const assigned = assignedIds.has(t.id);
      const borderColor = t.status === 'fault' ? '#f85149' : t.status === 'warning' ? '#d29922' : shot ? '#3fb950' : assigned ? '#388bfd' : '#54657e';
      const size = 32;

      const icon = L.icon({
        iconUrl: '/turbine-marker.png',
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        className: 'drone-turbine-icon',
      });

      const marker = L.marker([t.lat, t.lng], { icon, riseOnHover: true });
      const hiBadge = "<div style='display:inline-block;background:" + borderColor + ";color:#fff;font-size:8px;font-weight:700;border-radius:50%;width:15px;height:15px;text-align:center;line-height:15px;margin-left:4px;border:1px solid rgba(0,0,0,0.4);'>" + Math.round(t.hi_value) + "</div>";
      marker.bindTooltip(
        "<div style='font-size:11px;font-family:sans-serif'><b>" + t.name + "</b>" + hiBadge + "<br/>" +
        "<span style='color:#8fa2bc'>HI: " + t.hi_value.toFixed(0) + " | " + t.region + "</span><br/>" +
        "<span style='color:#8fa2bc'>" + (shot ? '已拍摄' : assigned ? '已分配' : '未分配') + "</span></div>",
        { direction: 'top', offset: [0, -14] },
      );
      marker.on('click', () => onTurbineRef.current?.(t));
      layer.addLayer(marker);
    });"""

content = content.replace(old_block, new_block)
print('TURBINE UPDATED')

# ── 2. Replace drone marker ──
old_drone_marker_start = "      // Drone position"
idx = content.index(old_drone_marker_start)
# Find the closing of this if block + addTo
old_drone_end = ".addTo(layer);"
end_search = content.index(old_drone_end, idx)
end_idx = end_search + len(old_drone_end)
old_drone_block = content[idx:end_idx]

new_drone_block = """      // Drone position
      if (drone.currentPosition && drone.status === 'flying') {
        const angle = drone.progress > 0 && drone.path.length >= 2
          ? (Math.atan2(
              drone.path[Math.min(Math.floor(drone.progress) + 1, drone.path.length - 1)].lat - drone.currentPosition.lat,
              drone.path[Math.min(Math.floor(drone.progress) + 1, drone.path.length - 1)].lng - drone.currentPosition.lng,
            ) * 180) / Math.PI
          : 0;
        L.marker([drone.currentPosition.lat, drone.currentPosition.lng], {
          icon: L.divIcon({
            className: '',
            html: '<div style="width:42px;height:42px;display:flex;align-items:center;justify-content:center;'
              + 'filter:drop-shadow(0 0 12px ' + color + ');transform:rotate(' + (angle - 90) + 'deg);">'
              + '<img src="/drone.png" width="38" height="38" style="display:block;" />'
              + '<span style="position:absolute;top:-4px;right:-8px;color:#fff;background:' + color + ';'
              + 'font-size:7px;font-weight:700;border-radius:50%;width:14px;height:14px;'
              + 'display:flex;align-items:center;justify-content:center;border:1px solid rgba(0,0,0,0.4);">' + drone.id + '</span></div>',
            iconSize: [42, 42], iconAnchor: [21, 21],
          }), zIndexOffset: 1000,
        }).bindTooltip(
          '<div style="font-size:11px"><b>' + drone.name + '</b><br/>'
          + '🔋 ' + drone.battery.toFixed(0) + '% | 📸 '
          + drone.completedTurbines.length + '/' + drone.assignedTurbines.length + '</div>',
          { direction: 'top' },
        ).addTo(layer);
      }"""

content = content.replace(old_drone_block, new_drone_block)
print('DRONE UPDATED')

# ── 3. Add takeoff markers before arrows ──
old_arrows = "      // Arrows\n      const step = Math.max(1, Math.floor(drone.path.length / 8));"
new_arrows = """      // Takeoff marker
      if (drone.path.length > 0) {
        const takeoff = drone.path[0];
        L.marker([takeoff.lat, takeoff.lng], {
          icon: L.icon({
            iconUrl: '/takeoff.png',
            iconSize: [28, 28],
            iconAnchor: [14, 28],
            className: '',
          }), zIndexOffset: 500,
        }).bindTooltip('<div style="font-size:10px"><b>' + drone.name + ' 起飞点</b></div>', { direction: 'top' }).addTo(layer);
      }

      // Arrows
      const step = Math.max(1, Math.floor(drone.path.length / 8));"""
content = content.replace(old_arrows, new_arrows)
print('TAKEOFF ADDED')

with open('frontend/src/components/Map/DroneMap.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('ALL DONE')
