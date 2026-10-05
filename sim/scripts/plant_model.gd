class_name PlantModel
extends RefCounted
## The sorting line as pure, deterministic state: step(dt) moves it on.
##
## No rendering and no networking, so it is tested directly. Positions are in
## pixels: the main belt runs left to right along BELT_Y, the side belt runs
## down from the diverter. A box's x is its centre on the main belt; on the
## side belt, side_pos is how far down it has travelled.

const BELT_Y: float = 300.0
const BELT_START: float = 60.0
const BELT_END: float = 900.0
const EYE_X: float = 380.0
const DIVERTER_X: float = 560.0
const SIDE_LENGTH: float = 260.0
const BOX_W: float = 40.0
const SHORT_H: float = 30.0
const TALL_H: float = 60.0
const BELT_SPEED: float = 120.0
const STROKE_TIME: float = 0.4
const PUSHER_HALF: float = 25.0
const SENSOR_INSET: float = 15.0


class Box:
	extends RefCounted
	var id: int
	var tall: bool
	var x: float
	var on_side: bool = false
	var side_pos: float = 0.0
	var jammed: bool = false

	func _init(box_id: int, is_tall: bool, start_x: float) -> void:
		id = box_id
		tall = is_tall
		x = start_x

	func spans(at: float) -> bool:
		return absf(x - at) < BOX_W / 2.0


var boxes: Array[Box] = []
var coils: PackedByteArray = PackedByteArray()
var stroke: float = 0.0  # diverter: 0 = home, 1 = fully out
var start_pressed: bool = false
var stop_pressed: bool = false
var estop_latched: bool = false
var spawned: int = 0
var max_boxes: int = 0  # 0 = keep spawning
var spawn_interval: float = 2.5
var exits: Dictionary[String, int] = {
	"main_short": 0, "main_tall": 0, "side_short": 0, "side_tall": 0
}

var _rng: RandomNumberGenerator = RandomNumberGenerator.new()
var _spawn_timer: float = 0.0


func _init(seed_value: int, box_limit: int = 0) -> void:
	_rng.seed = seed_value
	max_boxes = box_limit
	coils = Modbus.zeros(IoMap.COIL_COUNT)


## Take the PLC's coils; `online` false (watchdog tripped) forces all off.
func apply_coils(from_plc: PackedByteArray, online: bool) -> void:
	for i: int in range(IoMap.COIL_COUNT):
		coils[i] = from_plc[i] if online and i < from_plc.size() else 0


func step(dt: float) -> void:
	_spawn(dt)
	_move_diverter(dt)
	if coils[IoMap.CO_MAIN_MOTOR] != 0:
		_move_main(dt)
	if coils[IoMap.CO_SIDE_MOTOR] != 0:
		_move_side(dt)


func inputs() -> PackedByteArray:
	var di: PackedByteArray = Modbus.zeros(IoMap.INPUT_COUNT)
	di[IoMap.DI_START] = 1 if start_pressed else 0
	di[IoMap.DI_STOP_OK] = 0 if stop_pressed else 1
	di[IoMap.DI_ESTOP_OK] = 0 if estop_latched else 1
	di[IoMap.DI_LOW_BEAM] = 1 if _main_box_at(EYE_X, false) else 0
	di[IoMap.DI_HIGH_BEAM] = 1 if _main_box_at(EYE_X, true) else 0
	di[IoMap.DI_AT_DIVERTER] = 1 if _main_box_at(DIVERTER_X, false) else 0
	di[IoMap.DI_DIVERTER_OUT] = 1 if stroke >= 1.0 else 0
	di[IoMap.DI_DIVERTER_HOME] = 1 if stroke <= 0.0 else 0
	di[IoMap.DI_MAIN_EXIT] = 1 if _main_box_at(BELT_END - SENSOR_INSET, false) else 0
	di[IoMap.DI_SIDE_EXIT] = 1 if _side_box_near_end() else 0
	return di


func exited() -> int:
	var total: int = 0
	for key: String in exits:
		total += exits[key]
	return total


func missorted() -> int:
	return exits["main_tall"] + exits["side_short"]


## Boxes the diverter clipped or dropped mid-stroke. A box that is simply
## still on a belt is not counted here; tests check `boxes` for leftovers.
func jammed() -> int:
	var count: int = 0
	for box: Box in boxes:
		if box.jammed:
			count += 1
	return count


func _spawn(dt: float) -> void:
	_spawn_timer -= dt
	if _spawn_timer > 0.0 or (max_boxes > 0 and spawned >= max_boxes):
		return
	for box: Box in boxes:
		if not box.on_side and box.x - BOX_W / 2.0 < BELT_START + BOX_W:
			return  # infeed blocked: try again next step
	boxes.append(Box.new(spawned, _rng.randi_range(0, 1) == 1, BELT_START))
	spawned += 1
	_spawn_timer = spawn_interval


func _move_diverter(dt: float) -> void:
	var before: float = stroke
	var direction: float = 1.0 if coils[IoMap.CO_DIVERTER] != 0 else -1.0
	stroke = clampf(stroke + direction * dt / STROKE_TIME, 0.0, 1.0)
	_push(before)


## While the pusher moves out, a box centred on its face rides along and
## lands on the side belt at full stroke; a box it only clips is jammed.
func _push(before: float) -> void:
	if stroke <= 0.0:
		return
	for box: Box in boxes:
		if box.on_side or box.jammed:
			continue
		var offset: float = absf(box.x - DIVERTER_X)
		if offset >= PUSHER_HALF + BOX_W / 2.0:
			continue
		if offset > PUSHER_HALF or stroke < before:
			box.jammed = true
		elif stroke >= 1.0:
			box.on_side = true
			box.side_pos = 0.0


func _move_main(dt: float) -> void:
	var ordered: Array[Box] = _main_boxes()
	ordered.sort_custom(func(a: Box, b: Box) -> bool: return a.x > b.x)
	var limit: float = INF
	for box: Box in ordered:
		if box.jammed:
			limit = box.x - BOX_W
			continue
		var target: float = minf(box.x + BELT_SPEED * dt, limit)
		if stroke > 0.0 and absf(box.x - DIVERTER_X) <= PUSHER_HALF:
			target = box.x  # held against the pusher face
		elif stroke > 0.0 and box.x < DIVERTER_X:
			target = minf(target, DIVERTER_X - PUSHER_HALF - BOX_W / 2.0)
		box.x = maxf(box.x, target)
		limit = box.x - BOX_W
	for box: Box in ordered:
		if box.x - BOX_W / 2.0 > BELT_END:
			exits["main_tall" if box.tall else "main_short"] += 1
			boxes.erase(box)


func _move_side(dt: float) -> void:
	var done: Array[Box] = []
	for box: Box in boxes:
		if box.on_side:
			box.side_pos += BELT_SPEED * dt
			if box.side_pos - BOX_W / 2.0 > SIDE_LENGTH:
				done.append(box)
	for box: Box in done:
		exits["side_tall" if box.tall else "side_short"] += 1
		boxes.erase(box)


func _main_boxes() -> Array[Box]:
	var out: Array[Box] = []
	for box: Box in boxes:
		if not box.on_side:
			out.append(box)
	return out


func _main_box_at(at: float, tall_only: bool) -> bool:
	for box: Box in boxes:
		if not box.on_side and box.spans(at) and (box.tall or not tall_only):
			return true
	return false


func _side_box_near_end() -> bool:
	for box: Box in boxes:
		if box.on_side and absf(box.side_pos - (SIDE_LENGTH - SENSOR_INSET)) < BOX_W / 2.0:
			return true
	return false
