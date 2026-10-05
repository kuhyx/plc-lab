class_name ReferenceLogic
extends RefCounted
## The mock PLC's program: one scan turns the plant's inputs into coils.
##
## This is the reference the ST and ladder versions in projects/sorting-line/
## are written against; it is NOT the exercise answer key, just enough logic
## to prove the plant sorts. Same shape as a PLC program: latched run state,
## edge detection, a FIFO of box heights, and a small diverter sequence.

enum Phase { IDLE, PUSHING, RETURNING }

var running: bool = false
var phase: Phase = Phase.IDLE
var fifo: Array[bool] = []  # true = tall, oldest first

var _box_is_tall: bool = false
var _prev_low: bool = false
var _prev_at_diverter: bool = false


func scan(di: PackedByteArray) -> PackedByteArray:
	var stop_ok: bool = di[IoMap.DI_STOP_OK] != 0
	var estop_ok: bool = di[IoMap.DI_ESTOP_OK] != 0
	if not stop_ok or not estop_ok:
		running = false  # stop always wins
	elif di[IoMap.DI_START] != 0:
		running = true
	_track_heights(di)
	_sequence_diverter(di)
	var out: PackedByteArray = Modbus.zeros(IoMap.COIL_COUNT)
	out[IoMap.CO_MAIN_MOTOR] = 1 if running and phase == Phase.IDLE else 0
	out[IoMap.CO_SIDE_MOTOR] = 1 if running else 0
	out[IoMap.CO_DIVERTER] = 1 if running and phase == Phase.PUSHING else 0
	out[IoMap.CO_RUN_LAMP] = 1 if running else 0
	out[IoMap.CO_FAULT_LAMP] = 0 if estop_ok else 1
	return out


## A box is tall if the high beam is blocked at any point while the low beam
## is; its height is queued when it clears the low beam (falling edge).
func _track_heights(di: PackedByteArray) -> void:
	var low: bool = di[IoMap.DI_LOW_BEAM] != 0
	if low and di[IoMap.DI_HIGH_BEAM] != 0:
		_box_is_tall = true
	if _prev_low and not low:
		fifo.append(_box_is_tall)
		_box_is_tall = false
	_prev_low = low


## At the diverter (rising edge), the oldest queued height decides: tall
## stops the belt, pushes out to the limit, then retracts home.
func _sequence_diverter(di: PackedByteArray) -> void:
	var at_diverter: bool = di[IoMap.DI_AT_DIVERTER] != 0
	if at_diverter and not _prev_at_diverter and phase == Phase.IDLE and not fifo.is_empty():
		var tall: bool = fifo.pop_front()
		if tall:
			phase = Phase.PUSHING
	_prev_at_diverter = at_diverter
	if phase == Phase.PUSHING and di[IoMap.DI_DIVERTER_OUT] != 0:
		phase = Phase.RETURNING
	elif phase == Phase.RETURNING and di[IoMap.DI_DIVERTER_HOME] != 0:
		phase = Phase.IDLE
