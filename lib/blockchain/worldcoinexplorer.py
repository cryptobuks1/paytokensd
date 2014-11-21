'''
litecoinexplorer.com
'''
import logging

from lib import config, util

def get_host():
    if config.BLOCKCHAIN_SERVICE_CONNECT:
        return config.BLOCKCHAIN_SERVICE_CONNECT
    else:
        return 'http://www.litecoinexplorer.com' if config.TESTNET else 'http://www.litecoinexplorer.com'

def check():
    pass

def getinfo():
    result = util.get_url(get_host() + '/api/coindetails', abort_on_error=True)
    if 'TotalCoins' in result:
        return {
            "info": {
                "blocks": result['Blocks']
            }
        }
    
    return None

def listunspent(address):
    result = util.get_url(get_host() + '/api/address/{}'.format(address), abort_on_error=True)
    if 'status' in result and result['status'] == 'success':
        utxo = []
        for txo in result['data']['unspent']:
            newtxo = {
                'address': address,
                'txid': txo['tx'],
                'vout': txo['n'],
                'ts': 0,
                'scriptPubKey': txo['script'],
                'amount': float(txo['amount']),
                'confirmations': txo['confirmations'],
                'confirmationsFromCache': False
            }
            utxo.append(newtxo)
        return utxo
    
    return None

def getaddressinfo(address):
    infos = util.get_url(get_host() + '/api/address/{}'.format(address), abort_on_error=True)
    if 'Hash' in infos:
        #txs = util.get_url(get_host() + '/api/address/transaction/{}'.format(address), abort_on_error=True)
        #if 'status' in txs and txs['status'] == 'success':
            transactions = []
        #    for tx in txs['data']['txs']:
        #        transactions.append(tx['tx'])
            return {
                'addrStr': address,
                'balance': infos['Balance'],
                'balanceSat': infos['Balance'] * config.UNIT,
                'totalReceived': infos['TotalReceived'],
                'totalReceivedSat': infos['TotalReceived'] * config.UNIT,
                'unconfirmedBalance': 0,
                'unconfirmedBalanceSat': 0,
                'unconfirmedTxApperances': 0,
                'txApperances': 0,
                'transactions': transactions
            }
    
    return None

def gettransaction(tx_hash):
    url = get_host() + '/api/transaction/{}'.format(tx_hash)
    tx = util.get_url(url, abort_on_error=False)
    #assert tx and tx.get('status') and tx.get('code')
    #if tx['code'] == 404:
    #    return None
    #elif tx['code'] != 200:
    #    raise Exception("Invalid result (code %s), body: %s" % (tx['code'], tx))
    
    if 'Hash' in tx:
        valueOut = 0
        for vout in tx['Outputs']['Index']:
            valueOut += vout['Amount']
        return {
            'txid': tx_hash,
            'version': 0,
            'locktime': 0,
            'blockhash': tx['Block'], #will be None if not confirmed yet...
            'confirmations': 0,
            'time': tx['Time'],
            'blocktime': tx['Time'],
            'valueOut': valueOut,
            'vin': 0,
            'vout': 0
        }

    return None
