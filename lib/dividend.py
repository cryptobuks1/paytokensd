#! /usr/bin/python3

"""Pay out dividends."""

import struct
import decimal
D = decimal.Decimal

from . import (util, config, exceptions, litecoin, util)

FORMAT_1 = '>QQ'
LENGTH_1 = 8 + 8
FORMAT_2 = '>QQQ'
LENGTH_2 = 8 + 8 + 8
ID = 50


def validate (db, source, quantity_per_unit, asset, dividend_asset, block_index):
    cursor = db.cursor()
    problems = []

    if asset == config.LTC:
        problems.append('cannot pay dividends to holders of {}'.format(config.LTC))
    if asset == config.XPT:
        if (not block_index >= 317500) or block_index >= 320000 or config.TESTNET:   # Protocol change.
            problems.append('cannot pay dividends to holders of {}'.format(config.XPT))

    if quantity_per_unit <= 0: problems.append('non‐positive quantity per unit')

    # Examine asset.
    issuances = list(cursor.execute('''SELECT * FROM issuances WHERE (status = ? AND asset = ?) ORDER BY tx_index ASC''', ('valid', asset)))
    if not issuances:
        problems.append('no such asset, {}.'.format(asset))
        return None, None, problems, 0
    divisible = issuances[0]['divisible']

    # Only issuer can pay dividends.
    if block_index >= 320000 or config.TESTNET:   # Protocol change.
        if issuances[-1]['issuer'] != source:
            problems.append('only issuer can pay dividends')

    # Examine dividend asset.
    if dividend_asset in (config.LTC, config.XPT):
        dividend_divisible = True
    else:
        issuances = list(cursor.execute('''SELECT * FROM issuances WHERE (status = ? AND asset = ?)''', ('valid', dividend_asset)))
        if not issuances:
            problems.append('no such dividend asset, {}.'.format(dividend_asset))
            return None, None, problems, 0
        dividend_divisible = issuances[0]['divisible']

    # Calculate dividend quantities.
    holders = util.holders(db, asset)
    outputs = []
    addresses = []
    dividend_total = 0
    for holder in holders:

        if block_index < 294500 and not config.TESTNET: # Protocol change.
            if holder['escrow']: continue

        address = holder['address']
        address_quantity = holder['address_quantity']
        if block_index >= 296000 or config.TESTNET: # Protocol change.
            if address == source: continue

        dividend_quantity = address_quantity * quantity_per_unit
        if divisible: dividend_quantity /= config.UNIT
        if not dividend_divisible: dividend_quantity /= config.UNIT
        if dividend_asset == config.LTC and dividend_quantity < config.DEFAULT_MULTISIG_DUST_SIZE: continue    # A bit hackish.
        dividend_quantity = int(dividend_quantity)

        outputs.append({'address': address, 'address_quantity': address_quantity, 'dividend_quantity': dividend_quantity})
        addresses.append(address)
        dividend_total += dividend_quantity

    if not dividend_total: problems.append('zero dividend')

    if dividend_asset != config.LTC:
        balances = list(cursor.execute('''SELECT * FROM balances WHERE (address = ? AND asset = ?)''', (source, dividend_asset)))
        if not balances or balances[0]['quantity'] < dividend_total:
            problems.append('insufficient funds ({})'.format(dividend_asset))

    fee = 0
    if not problems and dividend_asset != config.LTC:
        holder_count = len(set(addresses))
        if block_index >= 330000 or config.TESTNET: # Protocol change.
            fee = int(0.0002 * config.UNIT * holder_count)
        if fee:
            balances = list(cursor.execute('''SELECT * FROM balances WHERE (address = ? AND asset = ?)''', (source, config.XPT)))
            if not balances or balances[0]['quantity'] < fee:
                problems.append('insufficient funds ({})'.format(config.XPT))

    cursor.close()
    return dividend_total, outputs, problems, fee

def compose (db, source, quantity_per_unit, asset, dividend_asset):

    dividend_total, outputs, problems, fee = validate(db, source, quantity_per_unit, asset, dividend_asset, util.last_block(db)['block_index'])
    if problems: raise exceptions.DividendError(problems)
    print('Total quantity to be distributed in dividends:', util.devise(db, dividend_total, dividend_asset, 'output'), dividend_asset)

    if dividend_asset == config.LTC:
        return (source, [(output['address'], output['dividend_quantity']) for output in outputs], None)

    asset_id = util.asset_id(asset)
    dividend_asset_id = util.asset_id(dividend_asset)
    data = struct.pack(config.TXTYPE_FORMAT, ID)
    data += struct.pack(FORMAT_2, quantity_per_unit, asset_id, dividend_asset_id)
    return (source, [], data)

def parse (db, tx, message):
    dividend_parse_cursor = db.cursor()

    # Unpack message.
    try:
        if (tx['block_index'] > 288150 or config.TESTNET) and len(message) == LENGTH_2:
            quantity_per_unit, asset_id, dividend_asset_id = struct.unpack(FORMAT_2, message)
            asset = util.asset_name(asset_id)
            dividend_asset = util.asset_name(dividend_asset_id)
            status = 'valid'
        elif len(message) == LENGTH_1:
            quantity_per_unit, asset_id = struct.unpack(FORMAT_1, message)
            asset = util.asset_name(asset_id)
            dividend_asset = config.XPT
            status = 'valid'
        else:
            raise exceptions.UnpackError
    except (exceptions.UnpackError, exceptions.AssetNameError, struct.error) as e:
        dividend_asset, quantity_per_unit, asset = None, None, None
        status = 'invalid: could not unpack'

    if dividend_asset == config.LTC:
        status = 'invalid: cannot pay {} dividends within protocol'.format(config.LTC)

    if status == 'valid':
        # For SQLite3
        quantity_per_unit = min(quantity_per_unit, config.MAX_INT)

        dividend_total, outputs, problems, fee = validate(db, tx['source'], quantity_per_unit, asset, dividend_asset, block_index=tx['block_index'])
        if problems: status = 'invalid: ' + '; '.join(problems)

    if status == 'valid':
        # Debit.
        util.debit(db, tx['block_index'], tx['source'], dividend_asset, dividend_total, action='dividend', event=tx['tx_hash'])
        if tx['block_index'] >= 330000 or config.TESTNET: # Protocol change.
            util.debit(db, tx['block_index'], tx['source'], config.XPT, fee, action='dividend fee', event=tx['tx_hash'])

        # Credit.
        for output in outputs:
            util.credit(db, tx['block_index'], output['address'], dividend_asset, output['dividend_quantity'], action='dividend', event=tx['tx_hash'])

    # Add parsed transaction to message-type–specific table.
    bindings = {
        'tx_index': tx['tx_index'],
        'tx_hash': tx['tx_hash'],
        'block_index': tx['block_index'],
        'source': tx['source'],
        'asset': asset,
        'dividend_asset': dividend_asset,
        'quantity_per_unit': quantity_per_unit,
        'fee_paid': fee,
        'status': status,
    }
    sql='insert into dividends values(:tx_index, :tx_hash, :block_index, :source, :asset, :dividend_asset, :quantity_per_unit, :fee_paid, :status)'
    dividend_parse_cursor.execute(sql, bindings)

    dividend_parse_cursor.close()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
