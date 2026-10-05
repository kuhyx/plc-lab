class_name ModbusClient
extends RefCounted
## A minimal blocking Modbus TCP master, used by the mock PLC.
##
## request() sends one frame and waits for the matching reply. `pump` is called
## while waiting, so a server living in the same process (the --mock run and
## the tests) can answer on the same thread without a deadlock.

const TIMEOUT_MS: int = 500
const UNIT_ID: int = 1

var _peer: StreamPeerTCP = StreamPeerTCP.new()
var _buffer: PackedByteArray = PackedByteArray()
var _transaction: int = 0


func connect_to(host: String, port: int) -> Error:
	return _peer.connect_to_host(host, port)


func close() -> void:
	_peer.disconnect_from_host()


## The reply PDU, or an empty array on timeout or a lost connection.
func request(pdu: PackedByteArray, pump: Callable) -> PackedByteArray:
	_transaction = (_transaction + 1) & 0xFFFF
	var payload: PackedByteArray = Modbus.frame(_transaction, UNIT_ID, pdu)
	var sent: bool = false
	var reply: PackedByteArray = PackedByteArray()
	var deadline: int = Time.get_ticks_msec() + TIMEOUT_MS
	while reply.is_empty() and Time.get_ticks_msec() < deadline:
		pump.call()
		var status: StreamPeerTCP.Status = _poll_status()
		if status != StreamPeerTCP.STATUS_CONNECTING and status != StreamPeerTCP.STATUS_CONNECTED:
			break  # lost, refused or never opened
		if status == StreamPeerTCP.STATUS_CONNECTED and not sent:
			sent = _peer.put_data(payload) == OK
			if not sent:
				break
		reply = _take_reply()
		if reply.is_empty():
			OS.delay_usec(100)
	return reply


func _poll_status() -> StreamPeerTCP.Status:
	if _peer.poll() != OK:
		return StreamPeerTCP.STATUS_ERROR
	return _peer.get_status()


func read_discrete_inputs(count: int, pump: Callable) -> PackedByteArray:
	var reply: PackedByteArray = request(
		Modbus.read_request(Modbus.FC_READ_DISCRETE_INPUTS, 0, count), pump
	)
	return Modbus.read_response_bits(reply, count)


func write_coils(bits: PackedByteArray, pump: Callable) -> bool:
	var reply: PackedByteArray = request(Modbus.write_coils_request(0, bits), pump)
	return reply.size() == 5 and reply[0] == Modbus.FC_WRITE_MULTIPLE_COILS


func _take_reply() -> PackedByteArray:
	var available: int = _peer.get_available_bytes()
	if available > 0:
		var got: Array = _peer.get_partial_data(available)
		if got[0] == OK:
			var chunk: PackedByteArray = got[1]
			_buffer.append_array(chunk)
	var size: int = Modbus.frame_size(_buffer)
	while size > 0:
		var frame_bytes: PackedByteArray = _buffer.slice(0, size)
		_buffer = _buffer.slice(size)
		if Modbus.transaction_of(frame_bytes) == _transaction:
			return Modbus.pdu_of(frame_bytes)
		size = Modbus.frame_size(_buffer)
	return PackedByteArray()
