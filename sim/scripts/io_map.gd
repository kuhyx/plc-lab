class_name IoMap
extends RefCounted
## The plant's Modbus addresses: the one place they are defined.
##
## The plant is a Modbus TCP *server* (remote I/O). OpenPLC v4 is the master:
## in the editor, add a Remote Device (Modbus, TCP, 127.0.0.1, PORT) with an
## FC 2 group over the discrete inputs and FC 5 groups for the coils; the
## editor assigns the local %IX/%QX addresses. projects/sorting-line/README.md
## carries the same table, and test_io_map.gd keeps the two in step.

const PORT: int = 1502

# Discrete inputs (FC 2): plant -> PLC. NC contacts read 1 when NOT pressed.
const DI_START: int = 0  # start button, NO: 1 while pressed
const DI_STOP_OK: int = 1  # stop button, NC: 0 while pressed
const DI_ESTOP_OK: int = 2  # e-stop, NC: 0 while latched in
const DI_LOW_BEAM: int = 3  # low photo-eye blocked (any box)
const DI_HIGH_BEAM: int = 4  # high photo-eye blocked (tall box only)
const DI_AT_DIVERTER: int = 5  # a box at the diverter
const DI_DIVERTER_OUT: int = 6  # diverter fully extended
const DI_DIVERTER_HOME: int = 7  # diverter fully retracted
const DI_MAIN_EXIT: int = 8  # a box at the end of the main belt
const DI_SIDE_EXIT: int = 9  # a box at the end of the side belt
const INPUT_COUNT: int = 10

# Coils (FC 1 read, FC 5 / FC 15 write): PLC -> plant.
const CO_MAIN_MOTOR: int = 0
const CO_SIDE_MOTOR: int = 1
const CO_DIVERTER: int = 2  # 1 = extend, 0 = retract
const CO_RUN_LAMP: int = 3
const CO_FAULT_LAMP: int = 4
const COIL_COUNT: int = 5

const INPUT_NAMES: PackedStringArray = [
	"start",
	"stop_ok",
	"estop_ok",
	"low_beam",
	"high_beam",
	"at_diverter",
	"diverter_out",
	"diverter_home",
	"main_exit",
	"side_exit",
]
const COIL_NAMES: PackedStringArray = [
	"main_motor",
	"side_motor",
	"diverter",
	"run_lamp",
	"fault_lamp",
]
