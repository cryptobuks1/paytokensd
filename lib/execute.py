#! /usr/bin/python3

# TODO: Ethereum (and Serpent?) licence

"""Execute arbitrary data as a smart contract."""

import struct
import binascii
import time
import logging

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
def memprint(data):
    line = binascii.hexlify(bytes(data))
    line = ' '.join([line[i:i+2].decode('ascii') for i in range(0, len(line), 2)])
    return line
def hexprint(x):
    if not x:
        return '<None>'
    if x != -1:
        return ('0x' + binascii.hexlify(bytes(x)).decode('ascii'))
    else:
        return 'OUT OF GAS'


GDEFAULT = 1
GMEMORY = 1
GSTORAGE = 100
GTXDATA = 5
GTXCOST = 500
TT255 = 2**255
TT256 = 2**256

OUT_OF_GAS = -1


def compose (db, source, contract_id, gas_price, gas_start, value, payload_hex):
    code = util.get_code(db, contract_id)
    payload = binascii.unhexlify(payload_hex)
    # TODO: Check start_gas, gas_price here?

    # Pack.
    data = struct.pack(config.TXTYPE_FORMAT, ID)
    curr_format = FORMAT + '{}s'.format(len(payload))
    data += struct.pack(curr_format, binascii.unhexlify(contract_id), gas_price, gas_start, value, payload)

    return (source, [], data)


def parse (db, tx, message):
    gas_cost = 0
    gas_remaining = 0
    output = None
    status = 'valid'

    try:
        # Unpack message.
        curr_format = FORMAT + '{}s'.format(len(message) - LENGTH)
        try:
            contract_id, gas_price, gas_start, value, payload = struct.unpack(curr_format, message)
        except (struct.error) as e:
            raise exceptions.UnpackError()

        contract_id = binascii.hexlify(contract_id).decode('utf-8')
        code = util.get_code(db, contract_id)
        # TODO: gas_price is an int

        # Check intrinsic gas used by contract.
        intrinsic_gas_used = GTXDATA * len(payload) + GTXCOST
        if gas_start < intrinsic_gas_used:
            raise exceptions.InsufficientStartGas(gas_start, intrinsic_gas_used)

        # Check cost required for down payment.
        total_initial_cost = value + gas_price * gas_start
        balance = util.get_balance(db, tx['source'], config.XCP) 
        if balance < total_initial_cost:
            raise exceptions.InsufficientBalance(balance, total_initial_cost)

        tx_dict = {'source': tx['source'],
                   'payload': binascii.hexlify(payload), 
                   'tx_hash': tx['tx_hash'],
                   'contract_id': contract_id,
                   'gas_price': gas_price,
                   'gas_start': util.devise(db, gas_start, config.XCP, 'output'),
                   'value': util.devise(db, value, config.XCP, 'output'),
                  }
        logging.debug('TX NEW {}'.format(tx_dict))

        util.debit(db, tx['block_index'], tx['source'], config.XCP, gas_price * gas_start, action='start execution', event=tx['tx_hash'])
        gas_cost += gas_price * gas_start

        message_gas = gas_start - intrinsic_gas_used
        class Message(object):
            def __init__(self, source, contract_id, value, gas, payload):
                self.source = source
                self.contract_id = contract_id
                self.value = value
                self.gas = gas
                self.data = payload
        message = Message(tx['source'], contract_id, value, message_gas, payload)

        # TODO: Make snapshot.
        logging.debug('CONTRACT PRE STATE (balance: {}, storage: {})'.format(util.devise(db, util.get_balance(db, contract_id, config.XCP), config.XCP, 'output'), hexprint(util.get_storage(db, contract_id))))

        # Apply message!
        result, gas_remaining, data = apply_msg(db, tx, message, code)
        assert gas_remaining >= 0
        logging.debug('RESULT {}'.format(result))
        logging.debug('DATA {}'.format(hexprint(data)))
        logging.debug('DECODED DATA {}'.format(util_rlp.decode_datalist(bytes(data))))

        if not result:  # 0 = OOG failure in both cases
            # TODO: Revert to snapshot.
            raise exceptions.OutOfGas
        logging.debug('CONTRACT POST STATE (balance: {}, storage: {})'.format(util.devise(db, util.get_balance(db, contract_id, config.XCP), config.XCP, 'output'), hexprint(util.get_storage(db, contract_id))))

        logging.debug('TX SUCCESS')
        gas_remaining = int(gas_remaining)  # TODO: BAD
        gas_used = gas_start - gas_remaining
        gas_cost -= gas_remaining

        # Return remaining gas to source.
        util.credit(db, tx['block_index'], tx['source'], config.XCP, gas_remaining, action='gas remaining', event=tx['tx_hash'])

        output = ''.join(map(chr, data))

        # TODO: Commit state. (Just don’t revert?!)
        status = 'finished'

        # NOTE
        # suicides = block.suicides
        # block.suicides = []
        # for s in suicides:
        #     block.del_account(s)

    except exceptions.UnpackError as e:
        contract_id, gas_price, gas_start, value, payload = None, None, None, None, None
        status = 'invalid: could not unpack'
        output = None
    except exceptions.ContractError as e:
        status = 'invalid: no such contract'
        output = None
    except exceptions.InsufficientStartGas as e:
        have, need = e.args
        logging.debug('Insufficient start gas: have {} and need {}'.format(have, need))
        status = 'invalid: insufficient start gas'
        output = None
    except exceptions.InsufficientBalance as e:
        have, need = e.args
        logging.debug('Insufficient balance: have {} and need {}'.format(have, need))
        status = 'invalid: insufficient balance'
        output = None
    except exceptions.OutOfGas as e:
        logging.debug('TX OUT_OF_GAS (gas_start: {}, gas_remaining: {})'.format(gas_start, gas_remaining))
        status = 'out of gas'
        output = None
    finally:
        if status == 'valid':   # TODO: eh…
            logging.debug('TX FINISHED (gas_remaining: {})'.format(gas_remaining))
        # Add parsed transaction to message-type–specific table.
        bindings = {
            'tx_index': tx['tx_index'],
            'tx_hash': tx['tx_hash'],
            'block_index': tx['block_index'],
            'source': tx['source'],
            'contract_id': contract_id,
            'gas_price': gas_price,
            'gas_start': gas_start,
            'gas_cost': gas_cost,
            'gas_remaining': gas_remaining,
            'value': value,
            'payload': payload,
            'output': output,
            'status': status
        }
        sql='insert into executions values(:tx_index, :tx_hash, :block_index, :source, :contract_id, :gas_price, :gas_start, :gas_cost, :gas_remaining, :value, :data, :output, :status)'
        cursor = db.cursor()
        cursor.execute(sql, bindings)
        cursor.close()



class Compustate():
    def __init__(self, **kwargs):
        self.memory = []
        self.stack = []
        self.pc = 0
        self.gas = 0
        for kw in kwargs:
            setattr(self, kw, kwargs[kw])
def apply_msg(db, tx, msg, code):
    # Transfer value, instaquit if not enough
    try:
        util.debit(db, tx['block_index'], tx['source'], config.XCP, msg.value, action='transfer value', event=tx['tx_hash'])
    except exceptions.BalanceError as e:
        return 1, msg.gas, []
    util.credit(db, tx['block_index'], msg.contract_id, config.XCP, msg.value, action='transfer value', event=tx['tx_hash'])

    logging.debug('DATA {}'.format(hexprint(msg.data)))
    logging.debug('DECODED DATA {}'.format(util_rlp.decode_datalist(msg.data))) # TODO: This can confuse endianness.
    logging.debug('CODE {}'.format(hexprint(code)))
    compustate = Compustate(gas=msg.gas)

    processed_code = [opcodes.get(c, ['INVALID', 0, 0, [], 0]) + [c] for c in code]
    # logging.debug('PROCESSED_CODE {}'.format(processed_code))

    # Main loop
    t = time.time()
    ops = 0
    while True:
        o = apply_op(db, tx, msg, processed_code, compustate)
        ops += 1
        if o is not None:
            logging.debug('MSG APPLIED (result: {}, gas_remained: {}, ops: {}, time_per_op: {})'.format(hexprint(o), compustate.gas, ops, (time.time() - t) / ops))
            if o == OUT_OF_GAS:
                return 0, compustate.gas, []
            else:
                return 1, compustate.gas, o


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
        pblogger.log('INSUFFICIENT STACK ERROR', op=op, needed=in_args,
                     available=len(compustate.stack))
        return []

    # out of gas error
    if fee > compustate.gas:
        return out_of_gas_exception('base_gas', fee, compustate, op)

    logging.debug('STK {}'.format(list(reversed(compustate.stack))))

    for i in range(0, len(compustate.memory), 16):
        memblk = compustate.memory[i:i+16]
        logging.debug('MEM {}'.format(memprint(memblk)))

    logging.debug('STORAGE {}'.format(hexprint(util.get_storage(db, msg.contract_id))))

    log_args = dict(pc=compustate.pc,
                    op=op,
                    stackargs=compustate.stack[-1:-in_args-1:-1],
                    gas=compustate.gas)
    if op[:4] == 'PUSH':
        ind = compustate.pc + 1
        log_args['value'] = \
            bytearray_to_int([x[-1] for x in processed_code[ind: ind + int(op[4:])]])
    elif op == 'CALLDATACOPY':
        log_args['data'] = binascii.hexlify(msg.data)
    logging.debug('OP {}'.format(log_args))

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
        data = ''.join(map(chr, mem[s0: s0 + s1]))
        stk.append(util_rlp.big_endian_to_int(sha3(data)))
    elif op == 'ADDRESS':
        stk.append(coerce_to_int(msg.to))
    elif op == 'BALANCE':
        stk.append(block.get_balance(coerce_addr_to_hex(stk.pop())))
    elif op == 'ORIGIN':
        stk.append(coerce_to_int(tx.sender))
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
        stk.append(tx.gasprice)
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
        stk.append(len(block.get_code(stk.pop()) or ''))
    elif op == 'EXTCODECOPY':
        addr, s1, s2, s3 = stk.pop(), stk.pop(), stk.pop(), stk.pop()
        extcode = block.get_code(addr) or ''
        if not mem_extend(mem, compustate, op, s1 + s3):
            return OUT_OF_GAS
        for i in range(s3):
            if s2 + i < len(extcode):
                mem[s1 + i] = ord(extcode[s2 + i])
            else:
                mem[s1 + i] = 0
    elif op == 'PREVHASH':
        stk.append(util_rlp.big_endian_to_int(block.prevhash))
    elif op == 'COINBASE':
        stk.append(util_rlp.big_endian_to_int(binascii.unhexlify(block.coinbase)))
    elif op == 'TIMESTAMP':
        stk.append(block.timestamp)
    elif op == 'NUMBER':
        stk.append(block.number)
    elif op == 'DIFFICULTY':
        stk.append(block.difficulty)
    elif op == 'GASLIMIT':
        stk.append(block.gas_limit)
    elif op == 'POP':
        stk.pop()
    elif op == 'MLOAD':
        s0 = stk.pop()
        if not mem_extend(mem, compustate, op, s0 + 32):
            return OUT_OF_GAS
        data = ''.join(map(chr, mem[s0: s0 + 32]))
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
        stk.append(block.get_storage_data(msg.to, stk.pop()))
    elif op == 'SSTORE':
        pass
        # NOTE
        # s0, s1 = stk.pop(), stk.pop()
        # pre_occupied = GSTORAGE if block.get_storage_data(msg.to, s0) else 0
        # post_occupied = GSTORAGE if s1 else 0
        # gascost = GSTORAGE + post_occupied - pre_occupied
        # if compustate.gas < gascost:
        #     out_of_gas_exception('sstore trie expansion', gascost, compustate, op)
        # compustate.gas -= gascost
        # block.set_storage_data(msg.to, s0, s1)
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
        data = ''.join(map(chr, mem[mstart: mstart + msz]))
        pblogger.log('SUB CONTRACT NEW', sender=msg.to, value=value, data=binascii.hexlify(data))
        create_msg = Message(msg.to, '', value, compustate.gas, data)
        addr, gas, code = create_contract(block, tx, create_msg)
        pblogger.log('SUB CONTRACT OUT', address=addr, code=code)
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
        to = binascii.hexlify(((b'\x00' * (32 - len(to))) + to)[12:])
        data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=value, gas=gas, data=binascii.hexlify(data))
        call_msg = Message(msg.to, to, value, gas, data)
        result, gas, data = apply_msg_send(db, block, tx, call_msg)
        pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data), expected=memoutsz)
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
        to = binascii.hexlify(((b'\x00' * (32 - len(to))) + to)[12:])
        data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        pblogger.log('POST NEW', sender=msg.to, to=to, value=value, gas=gas, data=binascii.hexlify(data))
        post_msg = Message(msg.to, to, value, gas, data)
        block.postqueue.append(post_msg)
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
        to = binascii.hexlify(((b'\x00' * (32 - len(to))) + to)[12:])
        data = ''.join(map(chr, mem[meminstart: meminstart + meminsz]))
        pblogger.log('SUB CALL NEW', sender=msg.to, to=to, value=value, gas=gas, data=binascii.hexlify(data))
        call_msg = Message(msg.to, msg.to, value, gas, data)
        result, gas, data = apply_msg(db, block, tx, call_msg, block.get_code(to))
        pblogger.log('SUB CALL OUT', result=result, data=data, length=len(data), expected=memoutsz)
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
        block.transfer_value(msg.to, to, block.get_balance(msg.to))
        block.suicides.append(msg.to)
        return []
    for a in stk:
        assert isinstance(a, int)


# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4