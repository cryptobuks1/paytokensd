#! /usr/bin/python3

# TODO: Ethereum (and Serpent?) licence

"""Execute arbitrary data as a smart contract."""

import struct
import binascii
import time
import logging
import string
import json
import pickle

from lib import (util, config, exceptions, bitcoin, util, util_rlp)

FORMAT = '>32sQQQ'
LENGTH = 56
ID = 101

# schema: [opcode, ins, outs, memuses, gas]
# memuses are written as an array of (start, len) pairs; values less than
# zero are taken as stackarg indices and values zero or greater are taken
# as literals
opcodes = {
    0x00: ['STOP', 0, 0, [], 0],
    0x01: ['ADD', 2, 1, [], 1],
    0x02: ['MUL', 2, 1, [], 1],
    0x03: ['SUB', 2, 1, [], 1],
    0x04: ['DIV', 2, 1, [], 1],
    0x05: ['SDIV', 2, 1, [], 1],
    0x06: ['MOD', 2, 1, [], 1],
    0x07: ['SMOD', 2, 1, [], 1],
    0x08: ['EXP', 2, 1, [], 1],
    0x09: ['NEG', 2, 1, [], 1],
    0x0a: ['LT', 2, 1, [], 1],
    0x0b: ['GT', 2, 1, [], 1],
    0x0c: ['SLT', 2, 1, [], 1],
    0x0d: ['SGT', 2, 1, [], 1],
    0x0e: ['EQ', 2, 1, [], 1],
    0x0f: ['NOT', 1, 1, [], 1],
    0x10: ['AND', 2, 1, [], 1],
    0x11: ['OR', 2, 1, [], 1],
    0x12: ['XOR', 2, 1, [], 1],
    0x13: ['BYTE', 2, 1, [], 1],
    0x14: ['ADDMOD', 3, 1, [], 1],
    0x15: ['MULMOD', 3, 1, [], 1],
    0x20: ['SHA3', 2, 1, [[-1, -2]], 20],
    0x30: ['ADDRESS', 0, 1, [], 1],
    0x31: ['BALANCE', 1, 1, [], 20],
    0x32: ['ORIGIN', 0, 1, [], 1],
    0x33: ['CALLER', 0, 1, [], 1],
    0x34: ['CALLVALUE', 0, 1, [], 1],
    0x35: ['CALLDATALOAD', 1, 1, [], 1],
    0x36: ['CALLDATASIZE', 0, 1, [], 1],
    0x37: ['CALLDATACOPY', 3, 0, [[-1, -3]], 1],
    0x38: ['CODESIZE', 0, 1, [], 1],
    0x39: ['CODECOPY', 3, 0, [[-1, -3]], 1],
    0x3a: ['GASPRICE', 0, 1, [], 1],
    0x40: ['PREVHASH', 0, 1, [], 1],
    0x41: ['COINBASE', 0, 1, [], 1],
    0x42: ['TIMESTAMP', 0, 1, [], 1],
    0x43: ['NUMBER', 0, 1, [], 1],
    0x44: ['DIFFICULTY', 0, 1, [], 1],
    0x45: ['GASLIMIT', 0, 1, [], 1],
    0x50: ['POP', 1, 0, [], 1],
    0x53: ['MLOAD', 1, 1, [[-1, 32]], 1],
    0x54: ['MSTORE', 2, 0, [[-1, 32]], 1],
    0x55: ['MSTORE8', 2, 0, [[-1, 1]], 1],
    0x56: ['SLOAD', 1, 1, [], 20],
    0x57: ['SSTORE', 2, 0, [], 0],
    0x58: ['JUMP', 1, 0, [], 1],
    0x59: ['JUMPI', 2, 0, [], 1],
    0x5a: ['PC', 0, 1, [], 1],
    0x5b: ['MSIZE', 0, 1, [], 1],
    0x5c: ['GAS', 0, 1, [], 1],
    0xf0: ['CREATE', 3, 1, [[-2, -3]], 100],
    0xf1: ['CALL', 7, 1, [[-4, -5], [-6, -7]], 20],
    0xf2: ['RETURN', 2, 1, [[-1, -2]], 1],
    0xf3: ['POST', 5, 1, [[-4, -5]], 20],
    0xf4: ['CALL_STATELESS', 7, 1, [[-4, -5], [-6, -7]], 20],
    0xff: ['SUICIDE', 1, 1, [], 0],
}

# TODO: Counterparty‐specific `OP_CODE`s
    # balance‐check
    # send
    # CPBAL
    # CPSEND

for i in range(1, 33):
    opcodes[0x5f + i] = ['PUSH' + str(i), 0, 1, [], 1]
for i in range(1, 17):
    opcodes[0x7f + i] = ['DUP' + str(i), i, i+1, [], 1]
    opcodes[0x8f + i] = ['SWAP' + str(i), i+1, i+1, [], 1]
reverse_opcodes = {}
for o in opcodes:
    reverse_opcodes[opcodes[o][0]] = o

sha3 = lambda x: sha3_256(x).digest()
def encode_int(v):
    # encodes an integer into serialization
    if not isinstance(v, int) or v < 0 or v >= 2 ** 256:
        raise Exception("Integer invalid or out of range")
    return util_rlp.int_to_big_endian(v)
def bytearray_to_int(arr):
    o = 0
    for a in arr:
        o = o * 256 + a
    return o

class ContractError(Exception):
    pass

def get_code (db, contract_id):
    cursor = db.cursor()
    cursor.execute('''SELECT * FROM contracts WHERE contract_id = ?''', (contract_id,))
    contracts = list(cursor)

    if not contracts:
        return b''
        # TODO: IMPORTANT raise ContractError('no such contract')
    else: code = contracts[0]['code']

    return code

def set_storage_data(db, contract_id, key, value):
    # TODO: This could all be done more elegantly, I think.

    # TODO
    # value = util_rlp.int_to_big_endian(value)
    # value = util_rlp.encode(value)

    key = key.to_bytes(32, byteorder='big')
    value = value.to_bytes(32, byteorder='big')

    cursor = db.cursor()

    cursor.execute('''SELECT * FROM storage WHERE contract_id = ? AND key = ?''', (contract_id, key))
    storages = list(cursor)
    if storages:    # Update value.
        bindings = {
            'contract_id': contract_id,
            'key': key,
            'value': value
            }
        sql='update storage set value = :value where contract_id = :contract_id and key = :key'
        cursor.execute(sql, bindings)
    else:           # Insert value.
        bindings = {
            'contract_id': contract_id,
            'key': key,
            'value': value
            }
        sql='insert into storage values(:contract_id, :key, :value)'
        cursor.execute(sql, bindings)

    storages = cursor.execute('''SELECT * FROM storage WHERE contract_id = ? AND key = ?''', (contract_id, key))


    return value

def get_storage_data(db, contract_id, key=None):
    cursor = db.cursor()

    if key == None:
        cursor.execute('''SELECT * FROM storage WHERE contract_id = ? ''', (contract_id,))
        storages = list(cursor)
        return storages

    # print('prekey', key)
    key = key.to_bytes(32, byteorder='big')
    cursor.execute('''SELECT * FROM storage WHERE contract_id = ? AND key = ?''', (contract_id, key))
    storages = list(cursor)
    # print('key', key)
    if not storages:
        return 0
    value = storages[0]['value']

    # TODO
    value = util_rlp.big_endian_to_int(value)
    # value = util_rlp.decode(value)

    return value

GDEFAULT = 1
GMEMORY = 1
GSTORAGE = 100
GTXDATA = 5
GTXCOST = 500
TT255 = 2**255
TT256 = 2**256

OUT_OF_GAS = -1

# TODO: Make fees proportional to money supply.

def memprint(data):
    line = binascii.hexlify(bytes(data))
    line = ' '.join([line[i:i+2].decode('ascii') for i in range(0, len(line), 2)])
    return line
def hexprint(x):
    assert type(x) in (bytes, list)
    if not x:
        return '<None>'
    if x != -1:
        return ('0x' + util.hexlify(bytes(x)))
    else:
        return 'OUT OF GAS'
def log (name, obj):
    assert type(obj) == dict

    # Convert binary.
    for key in obj.keys():
        if type(obj[key]) == bytes:
            obj[key] = hexprint(obj[key])

    # Truncate long lines.
    for key in obj.keys():
        if type(obj[key]) == str and len(obj[key]) > 120:
            obj[key] = obj[key][:60] + '…' + obj[key][-60:]

    # Sort
    if name == 'OP':
        keyorder = ['pc', 'gas', 'op', 'stackargs', 'value', 'stack']
        obj = sorted(obj.items(), key=lambda i:keyorder.index(i[0]))
    else:
        obj = sorted(obj.items())
    lines = ['{}: {}'.format(pair[0], pair[1]) for pair in obj]

    if 'op' == name.lower():
        string = str(lines).replace("'", "")[1:-1]
        logging.debug('\tOP ' + string)
    else:
        if name:
            logging.debug(name)
        for line in lines:
            logging.debug('\t' + str(line))


def compose (db, source, contract_id, gasprice, startgas, value, payload_hex):
    code = get_code(db, contract_id)
    payload = binascii.unhexlify(payload_hex)
    # TODO: Check start_gas, gasprice here?

    # Pack.
    data = struct.pack(config.TXTYPE_FORMAT, ID)
    curr_format = FORMAT + '{}s'.format(len(payload))
    data += struct.pack(curr_format, binascii.unhexlify(contract_id), gasprice, startgas, value, payload)

    return (source, [], data)


class HaltExecution(Exception): pass
class GasPriceTooLow(HaltExecution): pass
class InsufficientBalance(HaltExecution): pass
class InsufficientStartGas(HaltExecution): pass
class BlockGasLimitReached(HaltExecution): pass
class OutOfGas(HaltExecution): pass

def parse (db, tx, message):
    output = None
    status = 'valid'


    # TODO: unit tests!

    try:
        # Unpack message.
        curr_format = FORMAT + '{}s'.format(len(message) - LENGTH)
        try:
            contract_id, gasprice, startgas, value, payload = struct.unpack(curr_format, message)
        except (struct.error) as e:
            raise exceptions.UnpackError()

        contract_id = util.hexlify(contract_id)
        # TODO: gasprice is an int

        # ‘Apply transaction’!
        apply_transaction(db, tx, contract_id, gasprice, startgas, value, payload)

    except exceptions.UnpackError as e:
        contract_id, gasprice, startgas, value, payload = None, None, None, None, None
        status = 'invalid: could not unpack'
        output = None
    except util.ContractError as e:
        status = 'invalid: no such contract'
        contract_id = None
        output = None
    except InsufficientStartGas as e:
        have, need = e.args
        logging.debug('Insufficient start gas: have {} and need {}'.format(have, need))
        status = 'invalid: insufficient start gas'
        output = None
    except InsufficientBalance as e:
        have, need = e.args
        logging.debug('Insufficient balance: have {} and need {}'.format(have, need))
        status = 'invalid: insufficient balance'
        print(contract_id)
        output = None
    except OutOfGas as e:
        logging.debug('TX OUT_OF_GAS (startgas: {}, gas_remaining: {})'.format(startgas, gas_remaining))
        status = 'out of gas'
        output = None
    finally:

        # TODO: eh…
        if status == 'valid':
            logging.debug('TX FINISHED (gas_remaining: {})'.format(gas_remaining))

        # Add parsed transaction to message-type–specific table.
        bindings = {
            'tx_index': tx['tx_index'],
            'tx_hash': tx['tx_hash'],
            'block_index': tx['block_index'],
            'source': tx['source'],
            'contract_id': contract_id,
            'gasprice': gasprice,
            'startgas': startgas,
            'gas_cost': gas_cost,
            'gas_remaining': gas_remaining,
            'value': value,
            'payload': payload,
            'output': output,
            'status': status
        }
        sql='insert into executions values(:tx_index, :tx_hash, :block_index, :source, :contract_id, :gasprice, :startgas, :gas_cost, :gas_remaining, :value, :data, :output, :status)'
        cursor = db.cursor()
        cursor.execute(sql, bindings)


class Message(object):
    def __init__(self, sender, to, value, gas, data):
        assert type(sender) == str
        assert type(to) == str
        self.sender = sender
        self.to = to
        self.value = value
        self.gas = gas
        self.data = data
        # TODO: self.decoded_data = util_rlp.decode_datalist(data) # TODO: This can confuse endianness.

CREATE_CONTRACT_ADDRESS = ''

def apply_transaction(db, tx, to, gasprice, startgas, value, payload):
    assert type(payload) == bytes

    gas_remaining = 0
    gas_cost = 0

    # Check intrinsic gas used by contract.
    intrinsic_gas_used = GTXDATA * len(payload) + GTXCOST
    if startgas < intrinsic_gas_used:
        raise InsufficientStartGas(startgas, intrinsic_gas_used)

    # Check cost required for down payment.
    total_initial_cost = value + gasprice * startgas
    balance = util.get_balance(db, tx['source'], config.XCP) 
    if balance < total_initial_cost:
        raise InsufficientBalance(balance, total_initial_cost)

    tx_dict = {'sender': tx['source'],
               'data': util.hexlify(payload), 
               'to': to,
               'gasprice': gasprice,
               'startgas': startgas,
               'value': value}
    log('\nTX NEW', tx_dict)
    

    util.debit(db, tx['block_index'], tx['source'], config.XCP, gasprice * startgas, action='start execution', event=tx['tx_hash'])
    gas_cost += gasprice * startgas

    # TODO
    """
    ### BEGIN Computation ###
    logging.debug('SNAPSHOT')
    with db:
        # Apply message!
        result, gas_remaining, data = apply_msg(db, tx, code, tx['source'], contract_id, value, gas_available, payload)
        assert gas_remaining >= 0

        logging.debug('RESULT {}'.format(result))
        logging.debug('DATA {}'.format(hexprint(data)))
        logging.debug('DECODED DATA {}'.format(util_rlp.decode_datalist(bytes(data))))

        if not result:  # 0 = OOG failure in both cases
            logging.debug('REVERTING')  # Rollback.
            raise OutOfGas
    ### END Computation ###
    """

    ### NEW ###
    message_gas = startgas - intrinsic_gas_used
    message = Message(tx['source'], to, value, message_gas, payload)

    primary_result = None

    # Postqueue
    cursor = db.cursor()
    cursor.execute('''DELETE FROM postqueue''')
    cursor.execute('''INSERT INTO postqueue VALUES(:message)''', {'message': pickle.dumps(message)})
    def postqueue_pop():
        postqueues = list(cursor.execute('''SELECT * FROM postqueue ORDER BY rowid ASC'''))
        first_message_pickled = postqueues[0]['message']                                                # Get first entry.
        cursor.execute('''DELETE FROM postqueue WHERE rowid = (SELECT MIN(rowid) FROM postqueue)''')    # Delete first entry.
        return pickle.loads(first_message_pickled)

    while list(cursor.execute('''SELECT * FROM postqueue''')):
        message = postqueue_pop()
        if to and to != CREATE_CONTRACT_ADDRESS:
            result, gas_remained, data = apply_msg(db, tx, message, get_code(db, message.to))  # NOTE: apply_msg_send
        else:
            result, gas_remained, data = create_contract(db, tx, message)
        if not primary_result:
            primary_result = result, gas_remained, data



    result, gas_remained, data = primary_result

    assert gas_remained >= 0
    ### NEW ###

    logging.debug('TX SUCCESS\n\n\n')
    gas_remaining = int(gas_remaining)  # TODO: BAD
    gas_used = startgas - gas_remaining
    gas_cost -= gas_remaining

    # Return remaining gas to source.
    util.credit(db, tx['block_index'], tx['source'], config.XCP, gas_remaining, action='gas remaining', event=tx['tx_hash'])

    output = data
    status = 'finished'

    # Kill suicidal contract.
    cursor = db.cursor()
    suicides = list(cursor.execute('''SELECT * FROM suicides'''))
    for suicide in suicides:
        contract_id = suicide['contract_id']
        logging.debug('SUICIDING {}'.format(contract_id))
        cursor.execute('''DELETE FROM contracts WHERE contract_id = :contract_id''', {'contract_id': contract_id})
        cursor.execute('''DELETE FROM storage WHERE contract_id = :contract_id''', {'contract_id': contract_id})
    cursor.execute('''DELETE FROM suicides''')

    return True, output


def new_suicide(db, contract_id):
    cursor = db.cursor()
    cursor.execute('''INSERT INTO suicides VALUES(:contract_id)''', {'contract_id': contract_id})
    

def get_nonce(db, contract_id):
    cursor = db.cursor()
    nonces = list(cursor.execute('''SELECT * FROM nonces WHERE (contract_id = ?)''', (contract_id,)))
    if not nonces: return 0
    else: return nonces[0]['nonce']

def set_nonce(db, contract_id, nonce):
    cursor = db.cursor()
    cursor.execute('''SELECT * FROM nonces WHERE (contract_id = :contract_id)''', {'contract_id': contract_id})
    nonces = list(cursor)
    if not nonces:
        cursor.execute('''INSERT INTO nonces VALUES(:contract_id, :nonce)''', {'contract_id': contract_id, 'nonce': nonce})
    else:
        cursor.execute('''UPDATE contracts SET nonce = :nonce WHERE (contract_id = :contract_id)''', {'nonce': nonce, 'contract_id': contract_id})

def create_contract(db, tx, msg):
    if 'txid' in tx.keys():
        contract_id_seed = msg.sender + tx['txid']
        contract_id_seed = contract_id_seed.decode('ascii') # TODO
    else:
        nonce = get_nonce(db, msg.sender)
        contract_id_seed = msg.sender + str(nonce)  # TODO
        set_nonce(db, msg.sender, nonce + 1)
    contract_id = util.contract_sha3(contract_id_seed.encode('utf-8'))
    msg.to = contract_id
    code = msg.data

    # assert not get_code(db, contract_id) # TODO: check for duplicate contracts

    res, gas, dat = apply_msg(db, tx, msg, code)
    """
    if res:
        block.set_code(msg.to, ''.join(map(chr, dat)))
        return utils.coerce_to_int(msg.to), gas, dat
    else:
        if tx.sender != msg.sender:
            block.decrement_nonce(msg.sender)
        block.del_account(msg.to)
        return res, gas, dat
    """

    # Create contract with provided code.
    cursor = db.cursor()
    bindings = {'contract_id': contract_id, 'tx_index': None, 'tx_hash': None, 'block_index': 0, 'source': None, 'code': bytes(dat), 'nonce': 0}
    sql='insert into contracts values(:contract_id, :tx_index, :tx_hash, :block_index, :source, :code, :nonce)'
    cursor.execute(sql, bindings)
    return True, gas, contract_id


def get_msg_state(db, msg, code):
    msg_state = {}
    # msg_state['contract'] = msg.to
    msg_state['balance'] = util.get_balance(db, msg.to, config.XCP)
    storages = ['{}: {}'.format(hexprint(storage['key']), hexprint(storage['value'])) for storage in get_storage_data(db, msg.to)]
    msg_state['storage'] = storages
    msg_state['code'] = code
    return msg_state
    

class Compustate():
    def __init__(self, **kwargs):
        self.memory = []
        self.stack = []
        self.pc = 0
        self.gas = 0
        for kw in kwargs:
            setattr(self, kw, kwargs[kw])
def apply_msg(db, tx, msg, code):
    logging.debug('\n')
    new_dict = vars(msg).copy()
    new_dict.update(get_msg_state(db, msg, code))
    logging.debug('\nBEGIN MESSAGE') # TODO
    log('', new_dict)

    # Transfer value (instaquit if there isn’t enough).
    try:
        util.debit(db, tx['block_index'], msg.sender, config.XCP, msg.value, action='transfer value', event=tx['tx_hash'])
    except exceptions.BalanceError as e:
        raise e # TODO (avoid instaquit for debugging purposes)
        return 1, msg.gas, []
    util.credit(db, tx['block_index'], msg.to, config.XCP, msg.value, action='transfer value', event=tx['tx_hash'])

    processed_code = [opcodes.get(c, ['INVALID', 0, 0, [], 0]) + [c] for c in code]
    # logging.debug('PROCESSED_CODE {}'.format(processed_code))

    # Snapshot.
    try:
        with db:

            # Initialise compustate.
            compustate = Compustate(gas=msg.gas)

            # Main loop
            t = time.time()
            ops = 0
            logging.debug('')
            while True:
                data = apply_op(db, tx, msg, processed_code, compustate)
                ops += 1
                if data is not None:
                    gas_remaining = compustate.gas

                    # TODO: ugly
                    if data == OUT_OF_GAS:
                        data_printable = -1
                    else:
                        data_printable = bytes(data)

                    msg_applied = {'data (result)': data_printable,
                                   'sender': msg.sender,
                                   'to': msg.to,
                                   'gas': gas_remaining}
                    new_dict = msg_applied.copy()
                    new_dict.update(get_msg_state(db, msg, code))
                    logging.debug('')
                    log('', new_dict)
                    logging.debug('END MESSAGE\n')

                    if data == OUT_OF_GAS:
                        logging.debug('### REVERTING ###')
                        raise OutOfGas
                        result = 0
                        data = []
                    else:
                        result = 1

                    return result, gas_remaining, data
    except OutOfGas as e:
        result = 0
        data = []
        return result, gas_remaining, data
        


def get_opcode(code, index):
    return ord(code[index]) if index < len(code) else 0
def get_op_data(code, index):
    opcode = ord(code[index]) if index < len(code) else 0
    return opcodes.get(opcode, ['INVALID', 0, 0, [], 0])
def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)
def out_of_gas_exception(expense, fee, compustate, op):
    logging.debug('OUT OF GAS (expense: {}, needed: {}, available: {}, op: {}, stack: {})'.format(expense, fee, compustate.gas, op, list(reversed(compustate.stack))))
    return OUT_OF_GAS
def mem_extend(mem, compustate, op, newsize):
    if len(mem) < ceil32(newsize):
        m_extend = ceil32(newsize) - len(mem)
        mem.extend([0] * m_extend)
        memfee = GMEMORY * (m_extend // 32)
        compustate.gas -= memfee
        if compustate.gas < 0:
            out_of_gas_exception('mem_extend', memfee, compustate, op)
            return False
    return True
def to_signed(i):
    return i if i < TT255 else i - TT256

def coerce_to_int(x):
    if isinstance(x, int):
        return x
    elif len(x) == 40:  # TODO
        return util_rlp.big_endian_to_int(binascii.unhexlify(x))
    else:
        if type(x) != bytes:
            x = bytes(x, 'ascii')   # For addresses.
        return util_rlp.big_endian_to_int(x)

def zpad(x, l):
    return b'\x00' * max(0, l - len(x)) + x

def coerce_to_hex(x):
    if isinstance(x, int):
        return util.hexlify(zpad(util_rlp.int_to_big_endian(x), 20))
    elif len(x) == 40 or len(x) == 0:   # TODO
        return x
    else:
        return util.hexlify(zpad(x, 20)[-20:])


def apply_op(db, tx, msg, processed_code, compustate):
    # Does not include paying opfee.

    if compustate.pc >= len(processed_code):
        return []
    op, in_args, out_args, mem_grabs, fee, opcode = processed_code[compustate.pc]

    # print('APPLYING OP', op)
    # print('INARGS', in_args)
    # print('COMPUSTATE.STACK', compustate.stack)

    # empty stack error
    if in_args > len(compustate.stack):
        logging.debug('INSUFFICIENT STACK ERROR (op: {}, needed: {}, available: {})'.format(op, in_args,
                     len(compustate.stack)))
        return []

    # out of gas error
    if fee > compustate.gas:
        return out_of_gas_exception('base_gas', fee, compustate, op)

    for i in range(0, len(compustate.memory), 16):
        memblk = compustate.memory[i:i+16]
        # logging.debug('MEM {}'.format(memprint(memblk)))

    # logging.debug('\tSTORAGE\n\t\t' + '\n\t\t'.join(['{}: {}'.format(hexprint(storage['key']), hexprint(storage['value'])) for storage in get_storage_data(db, msg.to)]))

    # Log operation
    log_args = dict(pc=str(compustate.pc).zfill(3),
                    op=op,
                    stackargs=compustate.stack[-1:-in_args-1:-1],
                    stack=list(reversed(compustate.stack)),
                    gas=compustate.gas)
    if op[:4] == 'PUSH':
        ind = compustate.pc + 1
        log_args['value'] = \
            bytearray_to_int([x[-1] for x in processed_code[ind: ind + int(op[4:])]])
    elif op == 'CALLDATACOPY':
        log_args['data'] = binascii.hexlify(msg.data)
    log('OP', log_args)

    # Apply operation
    compustate.gas -= fee
    compustate.pc += 1
    stk = compustate.stack
    mem = compustate.memory
    if op == 'STOP' or op == 'INVALID':
        return []
    elif op == 'ADD':
        stk.append((stk.pop() + stk.pop()) % TT256)
    elif op == 'SUB':
        stk.append((stk.pop() - stk.pop()) % TT256)
    elif op == 'MUL':
        stk.append((stk.pop() * stk.pop()) % TT256)
    elif op == 'DIV':
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 // s1)
    elif op == 'MOD':
        s0, s1 = stk.pop(), stk.pop()
        stk.append(0 if s1 == 0 else s0 % s1)
    elif op == 'SDIV':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (s0 // s1) % TT256)
    elif op == 'SMOD':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(0 if s1 == 0 else (s0 % s1) % TT256)
    elif op == 'EXP':
        stk.append(pow(stk.pop(), stk.pop(), TT256))
    elif op == 'NEG':
        stk.append(-stk.pop() % TT256)
    elif op == 'LT':
        stk.append(1 if stk.pop() < stk.pop() else 0)
    elif op == 'GT':
        stk.append(1 if stk.pop() > stk.pop() else 0)
    elif op == 'SLT':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 < s1 else 0)
    elif op == 'SGT':
        s0, s1 = to_signed(stk.pop()), to_signed(stk.pop())
        stk.append(1 if s0 > s1 else 0)
    elif op == 'EQ':
        stk.append(1 if stk.pop() == stk.pop() else 0)
    elif op == 'NOT':
        stk.append(0 if stk.pop() else 1)
    elif op == 'AND':
        stk.append(stk.pop() & stk.pop())
    elif op == 'OR':
        stk.append(stk.pop() | stk.pop())
    elif op == 'XOR':
        stk.append(stk.pop() ^ stk.pop())
    elif op == 'BYTE':
        s0, s1 = stk.pop(), stk.pop()
        if s0 >= 32:
            stk.append(0)
        else:
            stk.append((s1 // 256 ** (31 - s0)) % 256)
    elif op == 'ADDMOD':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 + s1) % s2 if s2 else 0)
    elif op == 'MULMOD':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        stk.append((s0 * s1) % s2 if s2 else 0)
    elif op == 'SHA3':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0 + s1):
            return OUT_OF_GAS
        # NOTE data = ''.join(map(chr, mem[s0: s0 + s1]))
        data = bytes(mem[s0: s0 + s1])
        stk.append(util_rlp.big_endian_to_int(sha3(data)))
    elif op == 'ADDRESS':
        stk.append(coerce_to_int(msg.to))
    elif op == 'BALANCE':
        addr = stk.pop()
        addr = util.hexlify(addr.to_bytes(32, byteorder='big'))
        stk.append(util.get_balance(db, addr, config.XCP))
    elif op == 'ORIGIN':
        stk.append(coerce_to_int(tx['source']))
    elif op == 'CALLER':
        stk.append(coerce_to_int(msg.sender))
    elif op == 'CALLVALUE':
        stk.append(msg.value)
    elif op == 'CALLDATALOAD':
        s0 = stk.pop()
        if s0 >= len(msg.data):
            stk.append(0)
        else:
            dat = msg.data[s0: s0 + 32]
            """
            try:
                dat = binascii.unhexlify(dat.decode('ascii'))   # TODO
                dat = dat[::-1]
            except Exception:
                pass    # TODO
            print('DAT', dat)   # TODO
            print('DATA', dat, '\n\n\n\n\n')
            """
            stk.append(util_rlp.big_endian_to_int(dat + b'\x00' * (32 - len(dat))))
    elif op == 'CALLDATASIZE':
        stk.append(len(msg.data))
    elif op == 'CALLDATACOPY':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0 + s2):
            return OUT_OF_GAS
        for i in range(s2):
            if s1 + i < len(msg.data):
                mem[s0 + i] = ord(msg.data[s1 + i])
            else:
                mem[s0 + i] = 0
    elif op == 'GASPRICE':
        stk.append(tx['gasprice'])
    elif op == 'CODECOPY':
        s0, s1, s2 = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0 + s2):
            return OUT_OF_GAS
        for i in range(s2):
            if s1 + i < len(processed_code):
                mem[s0 + i] = processed_code[s1 + i][-1]
            else:
                mem[s0 + i] = 0
    elif op == 'EXTCODESIZE':
        stk.append(len(get_code(db, stk.pop()) or ''))
    elif op == 'EXTCODECOPY':
        addr, s1, s2, s3 = stk.pop(), stk.pop(), stk.pop(), stk.pop()
        extcode = get_code(db, addr) or ''
        if not mem_extend(mem, compustate, op, s1 + s3):
            return OUT_OF_GAS
        for i in range(s3):
            if s2 + i < len(extcode):
                mem[s1 + i] = ord(extcode[s2 + i])
            else:
                mem[s1 + i] = 0
    elif op == 'PREVHASH':
        # TODO
        stk.append(util_rlp.big_endian_to_int(block.prevhash))
    elif op == 'COINBASE':
        # TODO
        stk.append(util_rlp.big_endian_to_int(binascii.unhexlify(block.coinbase)))
    elif op == 'TIMESTAMP':
        stk.append(tx['timestamp'])
    elif op == 'NUMBER':
        # TODO
        stk.append(block.number)
    elif op == 'DIFFICULTY':
        # TODO
        stk.append(block.difficulty)
    elif op == 'GASLIMIT':
        # TODO
        stk.append(block.gas_limit)
    elif op == 'POP':
        stk.pop()
    elif op == 'MLOAD':
        s0 = stk.pop()
        if not mem_extend(mem, compustate, op, s0 + 32):
            return OUT_OF_GAS
        # NOTE data = ''.join(map(chr, mem[s0: s0 + 32]))
        data = bytes(mem[s0: s0 + 32])
        stk.append(util_rlp.big_endian_to_int(data))
    elif op == 'MSTORE':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0 + 32):
            return OUT_OF_GAS
        v = s1
        for i in range(31, -1, -1):
            mem[s0 + i] = v % 256
            v //= 256
    elif op == 'MSTORE8':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0 + 1):
            return OUT_OF_GAS
        mem[s0] = s1 % 256
    elif op == 'SLOAD':
        stk.append(get_storage_data(db, msg.to, stk.pop()))
    elif op == 'SSTORE':
        s0, s1 = stk.pop(), stk.pop()
        pre_occupied = GSTORAGE if get_storage_data(db, msg.to, s0) else 0
        post_occupied = GSTORAGE if s1 else 0
        gascost = GSTORAGE + post_occupied - pre_occupied
        if compustate.gas < gascost:
            out_of_gas_exception('sstore trie expansion', gascost, compustate, op)
        compustate.gas -= gascost
        set_storage_data(db, msg.to, s0, s1)
        print('SSTORE', msg.to, s0, s1)
    elif op == 'JUMP':
        compustate.pc = stk.pop()
    elif op == 'JUMPI':
        s0, s1 = stk.pop(), stk.pop()
        if s1:
            compustate.pc = s0
    elif op == 'PC':
        stk.append(compustate.pc)
    elif op == 'MSIZE':
        stk.append(len(mem))
    elif op == 'GAS':
        stk.append(compustate.gas)  # AFTER subtracting cost 1
    elif op[:4] == 'PUSH':
        pushnum = int(op[4:])
        dat = [x[-1] for x in processed_code[compustate.pc: compustate.pc + pushnum]]
        compustate.pc += pushnum
        stk.append(bytearray_to_int(dat))
    elif op[:3] == 'DUP':
        depth = int(op[3:])
        # DUP POP POP Debug hint
        is_debug = 1
        for i in range(depth):
            if compustate.pc + i < len(processed_code) and \
                    processed_code[compustate.pc + i][0] != 'POP':
                is_debug = 0
                break
        if is_debug:
            stackargs = [stk.pop() for i in range(depth)]
            print(' '.join(map(repr, stackargs)))
            stk.extend(reversed(stackargs))
            stk.append(stackargs[-1])
        else:
            stk.append(stk[-depth])
    elif op[:4] == 'SWAP':
        depth = int(op[4:])
        temp = stk[-depth-1]
        stk[-depth-1] = stk[-1]
        stk[-1] = temp
    elif op == 'CREATE':
        value, mstart, msz = stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, mstart + msz):
            return OUT_OF_GAS
        # NOTE data = ''.join(map(chr, mem[mstart: mstart + msz]))
        data = bytes(mem[mstart: mstart + msz])
        log('SUB CONTRACT NEW', {'sender': msg.to, 'value': value, 'data': util.hexlify(data)})
        create_msg = Message(msg.to, '', value, compustate.gas, data)
        result, gas, data = create_contract(db, tx, create_msg)
        # print('addr data', binascii.unhexlify(data))
        addr = coerce_to_int(binascii.unhexlify(data))
        log('SUB CONTRACT OUT', {'address': addr, 'code': data})
        if addr:
            stk.append(addr)
            compustate.gas = gas
        else:
            stk.append(0)
            compustate.gas = 0
    elif op == 'CALL':
        gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        new_memsize = max(meminstart + meminsz, memoutstart + memoutsz)
        if not mem_extend(mem, compustate, op, new_memsize):
            return OUT_OF_GAS
        if compustate.gas < gas:
            return out_of_gas_exception('subcall gas', gas, compustate, op)
        compustate.gas -= gas
        to = encode_int(to)
        to = util.hexlify(((b'\x00' * (32 - len(to))) + to)[12:])
        # NOTE data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        data = bytes(mem[meminstart: meminstart + meminsz])
        log('SUB CALL NEW', {'sender': msg.to, 'to': to, 'value': value, 'gas': gas, 'data': util.hexlify(data)})
        call_msg = Message(msg.to, to, value, gas, data)
        code = get_code(db, call_msg.to)
        result, gas, data = apply_msg(db, tx, call_msg, code)
        log('SUB CALL OUT', {'result': result, 'data': data, 'length': data, 'expected': memoutsz})
        if result == 0:
            stk.append(0)
        else:
            stk.append(1)
            compustate.gas += gas
            for i in range(min(len(data), memoutsz)):
                mem[memoutstart + i] = data[i]
    elif op == 'RETURN':
        s0, s1 = stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, s0 + s1):
            return OUT_OF_GAS
        return mem[s0: s0 + s1]
    elif op == 'POST':
        gas, to, value, meminstart, meminsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        if not mem_extend(mem, compustate, op, meminstart + meminsz):
            return OUT_OF_GAS
        if compustate.gas < gas:
            return out_of_gas_exception('subcall gas', gas, compustate, op)
        compustate.gas -= gas
        to = encode_int(to)
        to = util.hexlify(((b'\x00' * (32 - len(to))) + to)[12:])
        # NOTE data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        data = bytes(mem[meminstart: meminstart + meminsz])
        post_dict = {'sender': msg.to, 'to': to, 'value': value, 'gas': gas, 'data': util.hexlify(data)}
        log('POST NEW', post_dict)
        post_msg = Message(msg.to, to, value, gas, data)
        cursor = db.cursor()
        cursor.execute('''INSERT INTO postqueue VALUES(:message)''', {'message': pickle.dumps(post_msg)})
    elif op == 'CALL_STATELESS':
        gas, to, value, meminstart, meminsz, memoutstart, memoutsz = \
            stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop(), stk.pop()
        new_memsize = max(meminstart + meminsz, memoutstart + memoutsz)
        if not mem_extend(mem, compustate, op, new_memsize):
            return OUT_OF_GAS
        if compustate.gas < gas:
            return out_of_gas_exception('subcall gas', gas, compustate, op)
        compustate.gas -= gas
        to = encode_int(to)
        to = util.hexlify(((b'\x00' * (32 - len(to))) + to)[12:])
        # NOTE data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        data = bytes(mem[meminstart: meminstart + meminsz])
        logging.debug('SUB CALL NEW (sender: {}, to: {}, value: {}, gas: {}, data: {})'.format(msg.to, to, value, gas, util.hexlify(data)))
        call_msg = Message(msg.to, to, value, gas, data)
        code = get_code(db, call_msg.to)
        result, gas, data = apply_msg(db, tx, call_msg, code)
        logging.debug('SUB CALL OUT (result: {}, data: {}, length: {}, expected: {}'.format(result, data, len(data), memoutsz))
        if result == 0:
            stk.append(0)
        else:
            stk.append(1)
            compustate.gas += gas
            for i in range(min(len(data), memoutsz)):
                mem[memoutstart + i] = data[i]
    elif op == 'SUICIDE':
        to = encode_int(stk.pop())
        to = binascii.hexlify(((b'\x00' * (32 - len(to))) + to)[12:])
        transfer_value = util. get_balance(db, msg.to, config.XCP)
        util.debit(db, tx['block_index'], msg.to, config.XCP, transfer_value, action='suicide', event=tx['tx_hash'])
        util.credit(db, tx['block_index'], to, config.XCP, transfer_value, action='suicide', event=tx['tx_hash'])
        new_suicide(db, msg.to)
        return []
    for a in stk:
        assert isinstance(a, int)

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4