"""
3D Basketball Shooter  (Python / pygame port)
---------------------------------------------
Same game, variables, characters and colours as the browser version: 1v1,
with real fouls and free throws. pygame has no built-in 3D, so this file
does its own perspective projection.

Controls
  Left / Right : strafe          W : forward          Down : move back
  Up           : jump            F : DUNK (2 pts, mid-air near the hoop)
  Hold SPACE   : charge power    Release SPACE : shoot
  E : steal (when the CPU has the ball)
  L : level 1-2-3 (3 = hardest)  C : switch Gojo / Goku
  G : pause                      R : reset score       ESC : quit

Rules: shots from beyond the arc = 3 pts, inside = 2, dunk = 2.
After a made basket OR a miss the other side gets the ball. No dribbling.
A shot taken with the defender right on top of you has a chance of being
a shooting foul: a make becomes an AND-ONE (+1 free throw), a miss awards
2 or 3 free throws depending on where the shot was taken from. The
defender can close in on you but can't cross the midpoint between you and
the three-point line.

Requires:  pip install pygame
"""
import math, random, sys
import pygame

# ------------------------------------------------------------------ setup
W, H = 1000, 600
FOV = math.radians(60)
FPX = (H / 2) / math.tan(FOV / 2)          # focal length in pixels

def C(h):                                   # 0xRRGGBB -> (r,g,b)
    return ((h >> 16) & 255, (h >> 8) & 255, h & 255)

def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

BG = C(0x0B1220)

# ------------------------------------------------------------------ court / hoop
COURT_W, COURT_LEN = 15, 30
HOOP_Z, HOOP_X, RIM_Y, RIM_R = -13, 0, 3.05, 0.5
PLAYER_MIN_X, PLAYER_MAX_X = -COURT_W / 2 + 1, COURT_W / 2 - 1
PLAYER_MIN_Z, PLAYER_MAX_Z = HOOP_Z + 0.8, 2.5
GRAVITY = 9.6
SPEED_SCALE = 0.135
ANGLE = math.radians(52)
POWER_SPEED = 2.4
MOVE_SPEED = 4.2
JUMP_DURATION, JUMP_HEIGHT = 0.55, 1.4
DUNK_RANGE = 2.8
THREE_R = 6.6                                # matches the drawn three-point arc
FT_Z = HOOP_Z + 5.6                          # free-throw line, top of the key

LEVELS = {
    1: dict(err=0.32, dev=2.2, cf=3, wait=(5, 3), offSpd=1.3, defSpd=1.9, block=0.9, blockR=3.0, steal=0.8, cpuSteal=0.04, contest=1.0),
    2: dict(err=0.22, dev=1.4, cf=3, wait=(4, 3), offSpd=1.7, defSpd=2.6, block=0.8, blockR=2.8, steal=0.7, cpuSteal=0.12, contest=1.4),
    3: dict(err=0.07, dev=0.5, cf=2, wait=(2, 2), offSpd=2.5, defSpd=3.6, block=0.35, blockR=2.2, steal=0.4, cpuSteal=0.45, contest=2.4),
}
LV = 1
L = LEVELS[1]

# ------------------------------------------------------------------ state
player_x, player_z = 0.0, -2.0
facingX, facingZ = 0.0, -1.0
def_x, def_z = 0.0, HOOP_Z + 4
isJumping, jumpT, playerY = False, 0.0, 0.0
power, powerDir, charging = 0.0, 1, False
ballActive = False
bx = by = bz = bvx = bvy = bvz = prevBy = 0.0
score = cpuScore = attempts = 0
poss, shooter, shotPts = 'player', 'player', 2
cpuTimer, stealCd = 3.0, 0.0
cpuSpot = (0.0, -6.0)
currentChar = 'warrior'                      # 'warrior' = Goku, 'sorcerer' = Gojo
paused = False
msg, msgColor, msgTimer = '', (255, 255, 255), 0.0
keys_down = set()
screen = clock = fonts = None

# fouls / free throws
fouls = {'player': 0, 'cpu': 0}
isFouledShot = False
ft = None            # {'team', 'remaining', 'total'}
ftTimer = 0.0

# ------------------------------------------------------------------ game logic
def showMsg(text, color, frames=70):
    global msg, msgColor, msgTimer
    msg, msgColor, msgTimer = text, color, frames / 60.0

def hexc(s):
    return C(int(s.lstrip('#'), 16))

def faceHoop():
    global facingX, facingZ
    facingX, facingZ = HOOP_X - player_x, (HOOP_Z - 0.4) - player_z
    l = math.hypot(facingX, facingZ) or 1
    facingX, facingZ = facingX / l, facingZ / l

def ballRestPos():
    if poss == 'cpu':
        hx, hz = HOOP_X - def_x, (HOOP_Z - 0.4) - def_z
        l = math.hypot(hx, hz) or 1
        return def_x + hx / l * 0.5, 1.55, def_z + hz / l * 0.5
    return player_x + facingX * 0.5, 1.55 + playerY, player_z + facingZ * 0.5

def ptsFor(x, z):
    return 3 if math.hypot(x - HOOP_X, z - (HOOP_Z - 0.4)) > THREE_R else 2

def setPossession(team, reposition):
    global poss, ballActive, charging, power, player_x, player_z, def_x, def_z, cpuSpot, cpuTimer
    poss, ballActive, charging, power = team, False, False, 0.0
    if reposition:
        if team == 'player':
            player_x, player_z, def_x, def_z = 0, 1.5, 0, -7
        else:
            def_x, def_z, player_x, player_z = 0, 1.5, 0, -6
        faceHoop()
    if team == 'cpu':
        a, r = (random.random() - 0.5) * 2.2, 3.5 + random.random() * 5
        cpuSpot = (max(-6, min(6, math.sin(a) * r)), min(2, (HOOP_Z - 0.4) + math.cos(a) * r))
        cpuTimer = L['wait'][0] + random.random() * L['wait'][1]

def updateFoulHud():
    pass  # HUD text is built fresh from `fouls` each frame in draw_hud()

def startFreeThrows(team, count, label):
    global ft, player_x, player_z, def_x, def_z, isJumping, playerY, ballActive, charging, power, ftTimer
    ft = {'team': team, 'remaining': count, 'total': count}
    showMsg(label, hexc('#ffd23f') if team == 'player' else hexc('#ff9944'), 90)
    if team == 'player':
        player_x, player_z = HOOP_X, FT_Z
        isJumping, playerY = False, 0.0
        faceHoop()
        def_x, def_z = HOOP_X + 4, HOOP_Z + 1.2
    else:
        def_x, def_z = HOOP_X, FT_Z
        player_x, player_z = HOOP_X + 4, 1.2
        isJumping, playerY = False, 0.0
        ftTimer = 1.0 + random.random() * 0.6
    ballActive, charging, power = False, False, 0.0

def resolveFreeThrow(made):
    global ft, score, cpuScore, ballActive, charging, power, ftTimer
    if made:
        if ft['team'] == 'player': score += 1
        else: cpuScore += 1
        showMsg('FREE THROW MADE! +1', hexc('#5ee27a') if ft['team'] == 'player' else hexc('#ff7777'))
    else:
        showMsg('FREE THROW MISSED', hexc('#ffcc55'))
    ft['remaining'] -= 1
    if ft['remaining'] <= 0:
        other = 'cpu' if ft['team'] == 'player' else 'player'
        ft = None
        setPossession(other, True)
    else:
        ballActive, charging, power = False, False, 0.0
        if ft['team'] == 'cpu':
            ftTimer = 0.8 + random.random() * 0.5
        showMsg('FREE THROW %d of %d' % (ft['total'] - ft['remaining'] + 1, ft['total']),
                hexc('#ffd23f') if ft['team'] == 'player' else hexc('#ff9944'), 60)

def cpuFreeThrowShoot():
    global bx, by, bz, bvx, bvy, bvz, prevBy, ballActive
    dx, dz = HOOP_X - def_x, (HOOP_Z - 0.4) - def_z
    D = math.hypot(dx, dz)
    c = math.cos(ANGLE)
    den = c * c * (math.tan(ANGLE) * D - (RIM_Y - 1.55))
    v = math.sqrt((GRAVITY / 2) * D * D / den) if den > 0.1 else 6
    v *= 1 + (random.random() - 0.5) * L['err'] * 0.5  # uncontested, so more reliable
    bx, by, bz = ballRestPos()
    prevBy = by
    bvx, bvz, bvy = v * c * dx / D, v * c * dz / D, v * math.sin(ANGLE)
    ballActive = True

def ballResult(made):
    if ft is not None:
        resolveFreeThrow(made)
    else:
        endShot(made)

def endShot(made):
    global score, cpuScore, isFouledShot, fouls
    who = shooter
    other = 'cpu' if who == 'player' else 'player'
    if isFouledShot:
        isFouledShot = False
        fouls[other] += 1
        if made:
            if who == 'player': score += shotPts
            else: cpuScore += shotPts
            startFreeThrows(who, 1, ('AND-ONE! ' if who == 'player' else 'CPU AND-ONE! ') + '+1 free throw')
        else:
            startFreeThrows(who, shotPts, ('SHOOTING FOUL! ' if who == 'player' else 'FOUL ON YOU! ') +
                             '%d free throw%s' % (shotPts, 's' if shotPts > 1 else ''))
        return
    if made:
        if who == 'player': score += shotPts
        else: cpuScore += shotPts
        showMsg('THREE POINTER! +3' if shotPts == 3 else 'BUCKET! +%d' % shotPts,
                hexc('#5ee27a') if who == 'player' else hexc('#ff7777'))
    else:
        showMsg('MISS - CPU BALL' if who == 'player' else 'CPU MISSED - YOUR BALL',
                hexc('#ff5555') if who == 'player' else hexc('#5ee27a'))
    setPossession(other, True)

def shoot(releasePower):
    global attempts, shooter, shotPts, bx, by, bz, bvx, bvy, bvz, prevBy, ballActive, isFouledShot
    attempts += 1
    shooter, shotPts = 'player', ptsFor(player_x, player_z)
    dx, dz = HOOP_X - player_x, (HOOP_Z - 0.4) - player_z
    dist = math.hypot(dx, dz)
    dirX, dirZ = dx / dist, dz / dist
    contestDist = math.hypot(def_x - player_x, def_z - player_z)
    deviation = 0.0
    isFouledShot = False
    if contestDist < 2.6:
        deviation = (random.random() - 0.5) * ((2.6 - contestDist) / 2.6) * L['contest']
    if contestDist < 0.6: isFouledShot = random.random() < 0.35
    elif contestDist < 1.1: isFouledShot = random.random() < 0.15
    speed = max(releasePower, 4) * SPEED_SCALE
    bx, by, bz = ballRestPos()
    prevBy = by
    bvx = speed * math.cos(ANGLE) * dirX + deviation * 0.4
    bvz = speed * math.cos(ANGLE) * dirZ + deviation * 0.4
    bvy = speed * math.sin(ANGLE)
    ballActive = True

def cpuShoot():
    global shooter, shotPts, bx, by, bz, bvx, bvy, bvz, prevBy, ballActive, isFouledShot
    dx, dz = HOOP_X - def_x, (HOOP_Z - 0.4) - def_z
    D = math.hypot(dx, dz)
    pd = math.hypot(player_x - def_x, player_z - def_z)
    shooter, shotPts = 'cpu', ptsFor(def_x, def_z)
    isFouledShot = False
    if isJumping and pd < L['blockR'] and random.random() < L['block']:
        showMsg('BLOCKED!', hexc('#5ee27a'))
        setPossession('player', True)
        return
    if pd < 0.6: isFouledShot = random.random() < 0.3
    elif pd < 1.0: isFouledShot = random.random() < 0.12
    c = math.cos(ANGLE)
    den = c * c * (math.tan(ANGLE) * D - (RIM_Y - 1.55))
    v = math.sqrt((GRAVITY / 2) * D * D / den) if den > 0.1 else 6
    v *= 1 + (random.random() - 0.5) * L['err']
    contest = (2.6 - pd) / 2.6 if pd < 2.6 else 0
    dev = (random.random() - 0.5) * (L['dev'] + contest * L['cf'])
    bx, by, bz = ballRestPos()
    prevBy = by
    bvx = v * c * dx / D + dev * 0.4
    bvz = v * c * dz / D + dev * 0.4
    bvy = v * math.sin(ANGLE)
    ballActive = True

def attemptDunk():
    global attempts, shooter, shotPts, score, fouls
    if ft is not None or ballActive or poss != 'player':
        return
    dist = math.hypot(HOOP_X - player_x, (HOOP_Z - 0.4) - player_z)
    if not isJumping:
        showMsg('Jump first! (Up arrow)', hexc('#ffcc55')); return
    if dist > DUNK_RANGE:
        showMsg('Get closer to dunk!', hexc('#ffcc55')); return
    attempts += 1
    contestDist = math.hypot(def_x - player_x, def_z - player_z)
    fouled = contestDist < 1.0 and random.random() < 0.3
    blocked = (not fouled) and contestDist < 1.3 and random.random() < 0.45
    shooter, shotPts = 'player', 2
    name = 'GOJO' if currentChar == 'sorcerer' else 'GOKU'
    if blocked:
        showMsg("%s'S DUNK BLOCKED!" % name, hexc('#ff5555'))
        setPossession('cpu', True)
    else:
        score += 2
        if fouled:
            fouls['cpu'] += 1
            showMsg('%s DUNK + FOUL! +2' % name, hexc('#66aaff') if currentChar == 'sorcerer' else hexc('#ffaa22'))
            startFreeThrows('player', 1, 'AND-ONE! +1 free throw')
        else:
            showMsg('%s SLAM DUNK! +2' % name, hexc('#66aaff') if currentChar == 'sorcerer' else hexc('#ffaa22'))
            setPossession('cpu', True)

def updateBall(dt):
    global prevBy, bvx, bvy, bvz, bx, by, bz
    if not ballActive:
        return
    prevBy = by
    bvy -= GRAVITY * dt
    bx += bvx * dt; by += bvy * dt; bz += bvz * dt
    crossing = prevBy > RIM_Y >= by
    horiz = math.hypot(bx - HOOP_X, bz - (HOOP_Z - 0.4))
    if crossing and horiz < RIM_R * 0.9 and bvy < 0:
        ballResult(True); return
    if (HOOP_Z - 0.74) < bz < (HOOP_Z - 0.66) and abs(bx - HOOP_X) < 1.2 and 3.0 < by < 4.2 and bvz < 0:
        bvz *= -0.5; showMsg('OFF THE GLASS', hexc('#ff6666'))
    if abs(by - RIM_Y) < 0.15 and abs(horiz - RIM_R) < 0.15:
        bvy *= -0.35; bvx *= 0.6; bvz *= 0.6
    XM = COURT_W / 2 - 0.3
    if by < 0.16 or abs(bx) > XM or bz < HOOP_Z - 1.6 or bz > 3.2:
        ballResult(False)

def updateJump(dt):
    global isJumping, jumpT, playerY
    if not isJumping:
        return
    jumpT += dt
    t = jumpT / JUMP_DURATION
    if t >= 1: isJumping, playerY = False, 0.0
    else: playerY = math.sin(t * math.pi) * JUMP_HEIGHT

def updatePlayer(dt):
    global player_x, player_z, facingX, facingZ
    updateJump(dt)
    if ft is not None:
        return
    if ballActive and shooter == 'player':
        return
    mx = mz = 0
    if pygame.K_LEFT in keys_down: mx -= 1
    if pygame.K_RIGHT in keys_down: mx += 1
    if pygame.K_w in keys_down: mz -= 1
    if pygame.K_DOWN in keys_down: mz += 1
    if mx or mz:
        l = math.hypot(mx, mz); mx /= l; mz /= l
        player_x = max(PLAYER_MIN_X, min(PLAYER_MAX_X, player_x + mx * MOVE_SPEED * dt))
        player_z = max(PLAYER_MIN_Z, min(PLAYER_MAX_Z, player_z + mz * MOVE_SPEED * dt))
        faceHoop()

def updateFreeThrow(dt):
    global ftTimer
    if ft is None:
        return
    if ft['team'] == 'cpu' and not ballActive:
        ftTimer -= dt
        if ftTimer <= 0:
            ftTimer = 999
            cpuFreeThrowShoot()

def updateDefender(dt):
    global stealCd, def_x, def_z, cpuTimer
    if ft is not None:
        return
    stealCd = max(0, stealCd - dt)
    pd = math.hypot(def_x - player_x, def_z - player_z)
    spd = L['defSpd']
    if poss == 'cpu':
        tx, tz = cpuSpot
        spd = L['offSpd']
        if not ballActive:
            cpuTimer -= dt
            near = math.hypot(tx - def_x, tz - def_z) < 0.4
            if cpuTimer <= 0 and near:
                cpuShoot()
    else:
        tx = player_x
        tz = max(HOOP_Z + 0.6, player_z - 0.85)
        # beyond the arc, the defender can't close past the midpoint between the three-point line and you
        hoopZc = HOOP_Z - 0.4
        dPlayer = math.hypot(player_x - HOOP_X, player_z - hoopZc)
        if dPlayer > THREE_R:
            halfway = (dPlayer + THREE_R) / 2
            dirX, dirZ = (player_x - HOOP_X) / dPlayer, (player_z - hoopZc) / dPlayer
            natDist = math.hypot(tx - HOOP_X, tz - hoopZc)
            if natDist > halfway:
                tx, tz = HOOP_X + dirX * halfway, hoopZc + dirZ * halfway
        if not ballActive and pd < 0.9 and stealCd <= 0 and random.random() < dt * L['cpuSteal']:
            stealCd = 1.5
            showMsg('STOLEN!', hexc('#ff7777'))
            setPossession('cpu', False)
            return
    dx, dz = tx - def_x, tz - def_z
    d = math.hypot(dx, dz)
    if d > 0.05:
        st = min(d, spd * dt)
        def_x += dx / d * st; def_z += dz / d * st

def step(dt):
    global power, powerDir, msgTimer
    if paused:
        return
    if charging:
        power += POWER_SPEED * powerDir * 60 * dt * 0.6
        if power >= 100: power, powerDir = 100, -1
        elif power <= 0: power, powerDir = 0, 1
    updatePlayer(dt)
    updateDefender(dt)
    updateFreeThrow(dt)
    updateBall(dt)
    if msgTimer > 0:
        msgTimer = max(0, msgTimer - dt)

# ------------------------------------------------------------------ input
def togglePause():
    global paused
    paused = not paused
    if not paused:
        for k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_DOWN, pygame.K_w):
            keys_down.discard(k)

def handle_keydown(key):
    global charging, power, powerDir, isJumping, jumpT, currentChar, LV, L
    global score, cpuScore, attempts, stealCd, fouls, ft
    if key == pygame.K_g:
        togglePause(); return
    if paused:
        return
    keys_down.add(key)
    if key == pygame.K_SPACE:
        canShoot = (ft['team'] == 'player') if ft is not None else (poss == 'player')
        if not ballActive and not charging and canShoot:
            charging, power, powerDir = True, 0.0, 1
    if key == pygame.K_UP and not isJumping and ft is None:
        isJumping, jumpT = True, 0.0
    if key == pygame.K_f: attemptDunk()
    if key == pygame.K_c:
        currentChar = 'warrior' if currentChar == 'sorcerer' else 'sorcerer'
    if key == pygame.K_l:
        LV = LV % 3 + 1; L = LEVELS[LV]
        score = cpuScore = 0
        fouls = {'player': 0, 'cpu': 0}; ft = None
        setPossession('player', True)
        showMsg('LEVEL %d%s' % (LV, ' - HARDEST' if LV == 3 else ' - EASY' if LV == 1 else ''), hexc('#ffd23f'), 90)
    if key == pygame.K_e and ft is None and poss == 'cpu' and not ballActive and stealCd <= 0:
        stealCd = 0.6
        if math.hypot(def_x - player_x, def_z - player_z) < 2.6 and random.random() < L['steal']:
            showMsg('STEAL!', hexc('#5ee27a')); setPossession('player', False)
        else:
            showMsg('Steal failed', hexc('#ffcc55'))
    if key == pygame.K_r:
        cpuScore = 0
        score = attempts = 0
        fouls = {'player': 0, 'cpu': 0}; ft = None
        setPossession('player', True)

def handle_keyup(key):
    global charging, power
    keys_down.discard(key)
    if paused:
        return
    if key == pygame.K_SPACE and charging:
        charging = False
        shoot(power)
        power = 0.0

# ------------------------------------------------------------------ 3D camera
cam_pos = (0, 4.4, 4)
cam_f = cam_r = cam_u = (0, 0, -1)

def norm(v):
    l = math.sqrt(sum(c * c for c in v)) or 1
    return tuple(c / l for c in v)

def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

def update_camera():
    global cam_pos, cam_f, cam_r, cam_u
    cam_pos = (player_x * 0.6, 4.4, player_z + 6.5)
    cam_f = norm((HOOP_X - cam_pos[0], RIM_Y - cam_pos[1], HOOP_Z - cam_pos[2]))
    cam_r = norm(cross(cam_f, (0, 1, 0)))
    cam_u = cross(cam_r, cam_f)

def to_cam(p):
    d = (p[0] - cam_pos[0], p[1] - cam_pos[1], p[2] - cam_pos[2])
    return (dot(d, cam_r), dot(d, cam_u), dot(d, cam_f))

def proj_c(c):                                # camera-space -> screen
    return (W / 2 + FPX * c[0] / c[2], H / 2 - FPX * c[1] / c[2])

def proj(p):
    c = to_cam(p)
    if c[2] < 0.1: return None
    return proj_c(c) + (c[2],)

def fog(color, p):
    d = math.dist(p, cam_pos)
    return mix(color, BG, max(0, min(1, (d - 20) / 35)))

NEAR = 0.1
def clip_poly(cpts):
    out = []
    for i in range(len(cpts)):
        a, b = cpts[i], cpts[(i + 1) % len(cpts)]
        ain, bin_ = a[2] >= NEAR, b[2] >= NEAR
        if ain: out.append(a)
        if ain != bin_:
            t = (NEAR - a[2]) / (b[2] - a[2])
            out.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
    return out

def poly3d(pts, color):
    cp = clip_poly([to_cam(p) for p in pts])
    if len(cp) >= 3:
        pygame.draw.polygon(screen, color, [proj_c(c) for c in cp])

def line3d(a, b, color, width=1):
    ca, cb = to_cam(a), to_cam(b)
    if ca[2] < NEAR and cb[2] < NEAR: return
    if ca[2] < NEAR:
        t = (NEAR - ca[2]) / (cb[2] - ca[2]); ca = tuple(ca[k] + (cb[k] - ca[k]) * t for k in range(3))
    if cb[2] < NEAR:
        t = (NEAR - cb[2]) / (ca[2] - cb[2]); cb = tuple(cb[k] + (ca[k] - cb[k]) * t for k in range(3))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
    pygame.draw.line(screen, fog(color, mid), proj_c(ca), proj_c(cb), width)

def polyline3d(pts, color, width=1):
    for i in range(len(pts) - 1):
        line3d(pts[i], pts[i + 1], color, width)

def circle_pts(cx, cz, r, y=0.01, n=32, a0=0.0, a1=2 * math.pi):
    return [(cx + math.cos(a0 + (a1 - a0) * i / n) * r, y, cz + math.sin(a0 + (a1 - a0) * i / n) * r) for i in range(n + 1)]

# ------------------------------------------------------------------ court + hoop
def draw_court():
    screen.fill(BG)
    z0, z1 = 3, -COURT_LEN + 3
    base = C(0xC79A5B)
    for i in range(COURT_LEN):                # strips so the fog gradient looks right
        za, zb = z0 - i, z0 - i - 1
        poly3d([(-COURT_W / 2, 0, za), (COURT_W / 2, 0, za), (COURT_W / 2, 0, zb), (-COURT_W / 2, 0, zb)],
               fog(base, (0, 0, (za + zb) / 2)))
    plank = mix(C(0xC79A5B), C(0xB0803F), 0.5)
    x = -COURT_W / 2
    while x <= COURT_W / 2 + 1e-6:
        line3d((x, 0.005, z0), (x, 0.005, z1), plank); x += 0.9
    white = (255, 255, 255)
    for a, b in [((-7.5, 3), (7.5, 3)), ((-7.5, z1), (7.5, z1)), ((-7.5, 3), (-7.5, z1)), ((7.5, 3), (7.5, z1))]:
        line3d((a[0], 0.01, a[1]), (b[0], 0.01, b[1]), white, 2)
    zc = -COURT_LEN / 2 + 3
    line3d((-7.5, 0.01, zc), (7.5, 0.01, zc), white, 2)                 # half-court
    polyline3d(circle_pts(0, zc, 1.8), white, 2)                        # centre circle
    ring = C(0x1D4ED8)
    polyline3d(circle_pts(0, zc, 1.35, 0.012), ring, 3)
    polyline3d(circle_pts(0, zc, 1.2, 0.012), ring, 3)
    KEY_HALF_W, KEY_Z = 2.0, HOOP_Z + 5.6                               # the paint
    line3d((-KEY_HALF_W, .01, HOOP_Z - .4), (-KEY_HALF_W, .01, KEY_Z), white, 2)
    line3d((KEY_HALF_W, .01, HOOP_Z - .4), (KEY_HALF_W, .01, KEY_Z), white, 2)
    line3d((-KEY_HALF_W, .01, KEY_Z), (KEY_HALF_W, .01, KEY_Z), white, 2)
    polyline3d(circle_pts(0, KEY_Z, KEY_HALF_W, n=24), white, 2)        # free-throw circle
    arc = [(math.cos(a) * THREE_R, .01, (HOOP_Z - .4) + math.sin(a) * THREE_R)
           for a in [math.pi * 0.06 + (i / 40) * math.pi * 0.88 for i in range(41)]]
    arc = [p for p in arc if abs(p[0]) <= COURT_W / 2 - 0.3]
    polyline3d(arc, white, 2)                                           # three-point arc

def draw_hoop():
    hz = HOOP_Z
    a, b = proj((0, 0, hz - 1.1)), proj((0, 3.4, hz - 1.1))
    if a and b:
        pygame.draw.line(screen, fog(C(0x555555), (0, 1, hz)), a[:2], b[:2], max(2, int(0.3 * FPX / a[2])))
    bb = mix(BG, C(0xEEEEEE), 0.85)
    poly3d([(-1.2, 2.75, hz - .7), (1.2, 2.75, hz - .7), (1.2, 4.25, hz - .7), (-1.2, 4.25, hz - .7)], bb)
    rim = circle_pts(HOOP_X, hz - 0.4, RIM_R, RIM_Y, 24)
    for i in range(10):
        ang = (i / 10) * math.pi * 2
        line3d((HOOP_X + math.cos(ang) * RIM_R, RIM_Y, hz - .4 + math.sin(ang) * RIM_R),
               (HOOP_X + math.cos(ang) * RIM_R * .25, RIM_Y - .55, hz - .4 + math.sin(ang) * RIM_R * .25), (255, 255, 255))
    polyline3d(rim, C(0xFF5522), 4)

# ------------------------------------------------------------------ characters (cel-shaded primitives)
def rot_y(v, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return (v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c)

def spike(color, r, h, x, y, z, rz, rx):
    d = (-math.sin(rz), math.cos(rz) * math.cos(rx), math.cos(rz) * math.sin(rx))
    base = (x - d[0] * h / 2, y - d[1] * h / 2, z - d[2] * h / 2)
    tip = (x + d[0] * h / 2, y + d[1] * h / 2, z + d[2] * h / 2)
    return ('cone', base, tip, r, color, 0)

def base_parts(body, leg=0x222233):
    P = [('seg', (0, 1.55, 0), (0, .55, 0), .3, .24, body, True, 0),
         ('seg', (-.13, .755, 0), (-.13, .005, 0), .11, .09, leg, True, 0),
         ('seg', (.13, .755, 0), (.13, .005, 0), .11, .09, leg, True, 0)]
    s, c = math.sin(.2), math.cos(.2)
    P.append(('seg', (-.42 - s * .35, 1.05 + c * .35, 0), (-.42 + s * .35, 1.05 - c * .35, 0), .075, .065, body, True, 0))
    P.append(('seg', (.42 + s * .35, 1.05 + c * .35, 0), (.42 - s * .35, 1.05 - c * .35, 0), .075, .065, body, True, 0))
    P.append(('sph', (0, 1.85, 0), .34, 0xFFE0C4, 1, 1, True, 0))                       # big anime head
    for sx in (-1, 1):
        P.append(('sph', (sx * .12, 1.83, .315), .055, 0x111133, 1, 1.6, False, 0))     # eyes
    return P

def sorcerer_parts():                          # Gojo-style: white spiky hair, blindfold, high collar, blue orb
    P = base_parts(0x141A33, 0x0E1226)
    P.append(('seg', (0, 1.75, 0), (0, 1.45, 0), .21, .27, 0x0B0F22, True, .3))
    P.append(('seg', (0, 1.925, 0), (0, 1.795, 0), .352, .352, 0x0A0A0A, False, -.25))  # blindfold
    for i in range(9):
        a = i / 9 * math.pi * 2
        P.append(spike(0xFFFFFF, .09, .42 + random.Random(i).random() * .12, math.cos(a) * .2, 2.12, math.sin(a) * .2,
                       -math.cos(a) * .55, math.sin(a) * .55))
    P.append(spike(0xFFFFFF, .08, .4, 0, 2.28, 0, 0, 0))
    for bxp in (-.16, 0, .16):
        P.append(spike(0xFFFFFF, .07, .32, bxp, 2.0, .3, 0, .9))
    P.append(('orb', (.62, 1.2, .3), .16, 0x55CCFF, .85))
    return P

def warrior_parts():                           # Goku-style: huge spiky hair, orange gi, blue belt, golden aura
    P = base_parts(0xF0741A, 0xE8641A)
    B = 0x1F4FD0
    P.append(('seg', (0, .91, 0), (0, .79, 0), .3, .3, B, False, -.05))                 # belt
    P.append(('seg', (0, 1.58, 0), (0, 1.42, 0), .2, .26, B, True, .3))                # collar
    for sx in (-1, 1):
        P.append(('seg', (sx * .45, .79, 0), (sx * .45, .67, 0), .09, .09, B, False, -.05))
    for i in range(8):
        a = i / 8 * math.pi * 2
        P.append(spike(0x121212, .12, .5 + random.Random(i + 40).random() * .15, math.cos(a) * .2, 2.12, math.sin(a) * .2,
                       -math.cos(a) * .6, math.sin(a) * .6))
    P.append(spike(0x121212, .11, .5, 0, 2.25, 0, 0, 0))
    for bxp in (-.15, .15):
        P.append(spike(0x121212, .07, .28, bxp, 2.02, .3, 0, .8))
    P.append(('orb', (0, 1.1, 0), .95, 0xFFDD44, .10))                                   # aura
    return P

PARTS = {'sorcerer': sorcerer_parts(), 'warrior': warrior_parts(),
         'defender': base_parts(0x2266EE) + [('sph', (0, 2.0, 0), .36, 0x333333, 1, .6, True, 0)]}

items = []                                     # (depth, draw_fn)

def add_char(kind, px, py, pz, yaw):
    def W_(v):
        r = rot_y(v, yaw)
        return (px + r[0], py + r[1], pz + r[2])
    for part in PARTS[kind]:
        t = part[0]
        if t == 'seg':
            _, a, b, r1, r2, col, caps, bias = part
            A, B_ = W_(a), W_(b)
            m = ((A[0] + B_[0]) / 2, (A[1] + B_[1]) / 2, (A[2] + B_[2]) / 2)
            add_item(m, bias, lambda A=A, B_=B_, r1=r1, r2=r2, col=col, caps=caps: draw_seg(A, B_, r1, r2, col, caps))
        elif t == 'sph':
            _, c, r, col, sx, sy, outline, bias = part
            P_ = W_(c)
            add_item(P_, bias, lambda P_=P_, r=r, col=col, sx=sx, sy=sy, outline=outline: draw_sph(P_, r, col, sx, sy, outline))
        elif t == 'cone':
            _, a, b, r, col, bias = part
            A, B_ = W_(a), W_(b)
            m = ((A[0] + B_[0]) / 2, (A[1] + B_[1]) / 2, (A[2] + B_[2]) / 2)
            add_item(m, bias, lambda A=A, B_=B_, r=r, col=col: draw_cone(A, B_, r, col))
        elif t == 'orb':
            _, c, r, col, alpha = part
            P_ = W_(c)
            if r < .5: r *= 1 + .2 * math.sin(pygame.time.get_ticks() / 200)        # pulsing orb
            add_item(P_, -.3 if r < .5 else 1.5, lambda P_=P_, r=r, col=col, alpha=alpha: draw_glow(P_, r, col, alpha))

def add_item(p, bias, fn):
    items.append((to_cam(p)[2] + bias, fn))

INK = (0, 0, 0)
def draw_seg(A, B, r1, r2, col, caps):
    a, b = proj(A), proj(B)
    if not a or not b: return
    col = fog(C(col), A)
    for k, c in ((1.07, INK), (1.0, col)):
        p1r, p2r = r1 * k * FPX / a[2], r2 * k * FPX / b[2]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l = math.hypot(dx, dy) or 1
        nx, ny = -dy / l, dx / l
        pygame.draw.polygon(screen, c, [(a[0] + nx * p1r, a[1] + ny * p1r), (a[0] - nx * p1r, a[1] - ny * p1r),
                                        (b[0] - nx * p2r, b[1] - ny * p2r), (b[0] + nx * p2r, b[1] + ny * p2r)])
        if caps:
            pygame.draw.circle(screen, c, (int(a[0]), int(a[1])), max(1, int(p1r)))
            pygame.draw.circle(screen, c, (int(b[0]), int(b[1])), max(1, int(p2r)))

def draw_sph(P, r, col, sx=1, sy=1, outline=True):
    p = proj(P)
    if not p: return
    rp = r * FPX / p[2]
    col = fog(C(col), P)
    for k, c in (((1.07, INK), (1.0, col)) if outline else ((1.0, col),)):
        w, h = max(2, int(rp * 2 * k * sx)), max(2, int(rp * 2 * k * sy))
        pygame.draw.ellipse(screen, c, (int(p[0] - w / 2), int(p[1] - h / 2), w, h))

def draw_cone(A, B, r, col):
    a, b = proj(A), proj(B)
    if not a or not b: return
    col = fog(C(col), A)
    for k, c in ((1.15, INK), (1.0, col)):
        rp = r * k * FPX / a[2]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l = math.hypot(dx, dy) or 1
        nx, ny = -dy / l, dx / l
        tip = (b[0] + dx / l * (k - 1) * 8, b[1] + dy / l * (k - 1) * 8)
        pygame.draw.polygon(screen, c, [(a[0] + nx * rp, a[1] + ny * rp), (a[0] - nx * rp, a[1] - ny * rp), tip])

def draw_glow(P, r, col, alpha):
    p = proj(P)
    if not p: return
    rp = max(2, int(r * FPX / p[2]))
    s = pygame.Surface((rp * 2, rp * 2), pygame.SRCALPHA)
    pygame.draw.circle(s, C(col) + (int(255 * alpha),), (rp, rp), rp)
    screen.blit(s, (p[0] - rp, p[1] - rp))

def draw_ball_item():
    p = (bx, by, bz) if ballActive else ballRestPos()
    add_item(p, 0, lambda: draw_sph(p, .16, 0xD8722A, 1, 1, False))

def draw_characters():
    items.clear()
    yaw_p = math.atan2(facingX, facingZ)
    if poss == 'cpu': lx, lz = HOOP_X - def_x, (HOOP_Z - .4) - def_z
    else: lx, lz = player_x - def_x, player_z - def_z
    add_char(currentChar, player_x, playerY, player_z, yaw_p)
    add_char('defender', def_x, 0, def_z, math.atan2(lx, lz))
    draw_ball_item()
    for _, fn in sorted(items, key=lambda t: -t[0]):
        fn()

# ------------------------------------------------------------------ HUD
def hud_box(text, x, y, font, anchor='left'):
    surf = font.render(text, True, (255, 255, 255))
    w, h = surf.get_width() + 28, surf.get_height() + 16
    if anchor == 'center': x -= w // 2
    if anchor == 'right': x -= w
    box = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(box, (0, 0, 0, 90), (0, 0, w, h), border_radius=8)
    screen.blit(box, (x, y)); screen.blit(surf, (x + 14, y + 8))

def draw_hud():
    f15, f13, f44 = fonts
    hud_box('You %d – %d CPU  |  %s' % (score, cpuScore, 'Your ball' if poss == 'player' else 'CPU ball'), 16, 12, f15)
    hud_box('Playing as: %s (C)  |  Level %d (L)' % ('Gojo' if currentChar == 'sorcerer' else 'Goku', LV), W // 2, 12, f15, 'center')
    hud_box('Fouls: You %d – %d CPU' % (fouls['player'], fouls['cpu']), W // 2, 46, f13, 'center')
    hud_box('Defender distance: %.1f' % math.hypot(def_x - player_x, def_z - player_z), W - 16, 12, f15, 'right')
    help_ = ('Left/Right: strafe  |  W: forward  |  Down: back  |  Up: jump  |  F: DUNK (2 pts)  |  E: steal  |  '
             'Shots beyond the arc = 3 pts  |  Hold SPACE: charge shot  |  L: level 1-3  |  G: pause  |  C: switch character  |  R: reset score')
    words, line, lines = help_.split(' '), '', []
    for w_ in words:
        t = (line + ' ' + w_).strip()
        if f13.size(t)[0] > 560: lines.append(line); line = w_
        else: line = t
    lines.append(line)
    y = H - 58 - 15 * len(lines)
    for ln in lines:
        s = f13.render(ln, True, (204, 204, 204)); screen.blit(s, (W // 2 - s.get_width() // 2, y)); y += 15
    bx0, by0 = W // 2 - 140, H - 50
    bg = pygame.Surface((280, 26), pygame.SRCALPHA)
    pygame.draw.rect(bg, (30, 30, 40, 180), (0, 0, 280, 26), border_radius=8)
    screen.blit(bg, (bx0, by0))
    if power > 0:
        col = (76, 175, 80) if 55 <= power <= 85 else ((255, 165, 0) if 30 <= power <= 95 else (224, 85, 85))
        pygame.draw.rect(screen, col, (bx0 + 2, by0 + 2, int(276 * power / 100), 22), border_radius=6)
    pygame.draw.rect(screen, (255, 255, 255), (bx0, by0, 280, 26), 2, border_radius=8)
    text, color, alpha = (('PAUSED - press G to resume', (255, 255, 255), 1.0) if paused
                          else (msg, msgColor, min(1.0, msgTimer / 0.2)) if msgTimer > 0 else (None, None, 0))
    if text:
        s = f44.render(text, True, color); s.set_alpha(int(255 * alpha))
        screen.blit(s, (W // 2 - s.get_width() // 2, int(H * 0.38) - s.get_height() // 2))

def render():
    update_camera()
    draw_court()
    draw_hoop()
    draw_characters()
    draw_hud()

# ------------------------------------------------------------------ main
def init(headless=False):
    global screen, clock, fonts
    pygame.init()
    pygame.display.set_caption('3D Basketball Shooter')
    screen = pygame.display.set_mode((W, H))
    clock = pygame.time.Clock()
    fonts = (pygame.font.SysFont('arial', 15, bold=True), pygame.font.SysFont('arial', 13),
             pygame.font.SysFont('arial', 44, bold=True))
    faceHoop()

def main():
    init()
    running = True
    while running:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        for e in pygame.event.get():
            if e.type == pygame.QUIT: running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE: running = False
                else: handle_keydown(e.key)
            elif e.type == pygame.KEYUP: handle_keyup(e.key)
        step(dt)
        render()
        pygame.display.flip()
    pygame.quit(); sys.exit()

if __name__ == '__main__':
    main()
