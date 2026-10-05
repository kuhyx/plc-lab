class_name PlantPainter
extends RefCounted
## Draws a PlantModel with plain shapes; colours are the shared design tokens
## (~/src/utils/unified-design-system/DOCS-tokens.md).

const INK: Color = Color("#211D1B")
const RAISED: Color = Color("#38312E")
const LINE: Color = Color("#463E3A")
const TEXT: Color = Color("#ECEAE9")
const MUTED: Color = Color("#AAA09A")
const ACCENT: Color = Color("#B8862E")
const SUCCESS: Color = Color("#8A9A3C")
const WARNING: Color = Color("#E0A63C")
const DANGER: Color = Color("#E2585F")
const SHORT_BOX: Color = Color("#398FC0")

const BELT_W: float = 50.0
const BUTTON_R: float = 26.0
const START_AT: Vector2 = Vector2(1000.0, 120.0)
const STOP_AT: Vector2 = Vector2(1080.0, 120.0)
const ESTOP_AT: Vector2 = Vector2(1180.0, 120.0)
const RUN_LAMP_AT: Vector2 = Vector2(1000.0, 230.0)
const FAULT_LAMP_AT: Vector2 = Vector2(1080.0, 230.0)


static func draw(canvas: CanvasItem, model: PlantModel, status: String) -> void:
	canvas.draw_rect(Rect2(0.0, 0.0, 1280.0, 720.0), INK)
	_draw_belts(canvas, model)
	_draw_beams(canvas, model.inputs())
	for box: PlantModel.Box in model.boxes:
		_draw_box(canvas, box)
	_draw_pusher(canvas, model.stroke)
	_draw_panel(canvas, model)
	_text(canvas, Vector2(40.0, 680.0), status, MUTED)


static func _draw_belts(canvas: CanvasItem, model: PlantModel) -> void:
	var main: Rect2 = Rect2(
		PlantModel.BELT_START,
		PlantModel.BELT_Y - BELT_W / 2.0,
		PlantModel.BELT_END - PlantModel.BELT_START,
		BELT_W
	)
	var side: Rect2 = Rect2(
		PlantModel.DIVERTER_X - BELT_W / 2.0,
		PlantModel.BELT_Y + BELT_W / 2.0,
		BELT_W,
		PlantModel.SIDE_LENGTH
	)
	for belt: Rect2 in [main, side]:
		canvas.draw_rect(belt, RAISED)
		canvas.draw_rect(belt, LINE, false, 2.0)
	var main_on: bool = model.coils[IoMap.CO_MAIN_MOTOR] != 0
	var side_on: bool = model.coils[IoMap.CO_SIDE_MOTOR] != 0
	_text(canvas, Vector2(PlantModel.BELT_START, 250.0), "main belt", SUCCESS if main_on else MUTED)
	_text(canvas, Vector2(610.0, 560.0), "side belt", SUCCESS if side_on else MUTED)


static func _draw_beams(canvas: CanvasItem, di: PackedByteArray) -> void:
	var y: float = PlantModel.BELT_Y + BELT_W / 2.0
	var low: float = y - 15.0
	var high: float = y - 45.0
	_beam(canvas, PlantModel.EYE_X, low, di[IoMap.DI_LOW_BEAM] != 0)
	_beam(canvas, PlantModel.EYE_X, high, di[IoMap.DI_HIGH_BEAM] != 0)
	_beam(canvas, PlantModel.DIVERTER_X, low, di[IoMap.DI_AT_DIVERTER] != 0)
	_beam(canvas, PlantModel.BELT_END - PlantModel.SENSOR_INSET, low, di[IoMap.DI_MAIN_EXIT] != 0)


static func _beam(canvas: CanvasItem, x: float, y: float, blocked: bool) -> void:
	canvas.draw_line(Vector2(x, y - 4.0), Vector2(x, y + 4.0), WARNING if blocked else LINE, 3.0)
	canvas.draw_circle(Vector2(x, y), 4.0, WARNING if blocked else MUTED)


static func _draw_box(canvas: CanvasItem, box: PlantModel.Box) -> void:
	var h: float = PlantModel.TALL_H if box.tall else PlantModel.SHORT_H
	var bottom: Vector2 = Vector2(box.x, PlantModel.BELT_Y + BELT_W / 2.0)
	if box.on_side:
		bottom = Vector2(PlantModel.DIVERTER_X, PlantModel.BELT_Y + BELT_W + box.side_pos)
	var rect: Rect2 = Rect2(bottom.x - PlantModel.BOX_W / 2.0, bottom.y - h, PlantModel.BOX_W, h)
	canvas.draw_rect(rect, ACCENT if box.tall else SHORT_BOX)
	canvas.draw_rect(rect, DANGER if box.jammed else INK, false, 2.0)


static func _draw_pusher(canvas: CanvasItem, stroke: float) -> void:
	var y: float = PlantModel.BELT_Y - BELT_W / 2.0 - 70.0 + stroke * 60.0
	var face: Rect2 = Rect2(
		PlantModel.DIVERTER_X - PlantModel.PUSHER_HALF, y, PlantModel.PUSHER_HALF * 2.0, 10.0
	)
	var rod_top: Vector2 = Vector2(PlantModel.DIVERTER_X, 150.0)
	canvas.draw_line(rod_top, Vector2(PlantModel.DIVERTER_X, y), MUTED, 4.0)
	canvas.draw_rect(face, TEXT)


static func _draw_panel(canvas: CanvasItem, model: PlantModel) -> void:
	canvas.draw_circle(
		START_AT, BUTTON_R, SUCCESS.darkened(0.3) if model.start_pressed else SUCCESS
	)
	canvas.draw_circle(STOP_AT, BUTTON_R, DANGER.darkened(0.3) if model.stop_pressed else DANGER)
	canvas.draw_circle(ESTOP_AT, BUTTON_R + 6.0, WARNING)
	canvas.draw_circle(ESTOP_AT, BUTTON_R, DANGER.darkened(0.4) if model.estop_latched else DANGER)
	_text(canvas, START_AT + Vector2(-20.0, 46.0), "start S", TEXT)
	_text(canvas, STOP_AT + Vector2(-20.0, 46.0), "stop X", TEXT)
	_text(canvas, ESTOP_AT + Vector2(-26.0, 52.0), "e-stop E", TEXT)
	var run_on: bool = model.coils[IoMap.CO_RUN_LAMP] != 0
	var fault_on: bool = model.coils[IoMap.CO_FAULT_LAMP] != 0
	canvas.draw_circle(RUN_LAMP_AT, 14.0, SUCCESS if run_on else RAISED)
	canvas.draw_circle(FAULT_LAMP_AT, 14.0, DANGER if fault_on else RAISED)
	_text(canvas, RUN_LAMP_AT + Vector2(-12.0, 34.0), "run", TEXT)
	_text(canvas, FAULT_LAMP_AT + Vector2(-16.0, 34.0), "fault", TEXT)
	var lines: PackedStringArray = [
		"main exit: short %d, tall %d" % [model.exits["main_short"], model.exits["main_tall"]],
		"side exit: short %d, tall %d" % [model.exits["side_short"], model.exits["side_tall"]],
		"missorted %d, jammed %d" % [model.missorted(), model.jammed()],
	]
	for i: int in range(lines.size()):
		_text(canvas, Vector2(960.0, 330.0 + 28.0 * i), lines[i], TEXT)


static func _text(canvas: CanvasItem, at: Vector2, text: String, color: Color) -> void:
	canvas.draw_string(ThemeDB.fallback_font, at, text, HORIZONTAL_ALIGNMENT_LEFT, -1.0, 16, color)
