[![Build Status](https://travis-ci.org/CzarcraftDLA/czarcraftd.svg?branch=develop)](https://travis-ci.org/CzarcraftDLA/czarcraftd)

# Description
Czarcraft is a protocol for the creation and use of decentralised financial
instruments such as asset exchanges, contracts for difference and dividend
payments. It uses Litecoin as a transport layer. The contents of this
repository, `czarcraftd`, constitute the reference implementation of the
protocol.

The Czarcraft protocol specification may be found at
<https://github.com/CzarcraftDLA/Czarcraft>.

# Dependencies
* [Python 3](http://python.org)
* Python 3 packages: apsw, requests, appdirs, prettytable, python-dateutil, json-rpc, tornado, flask, Flask-HTTPAuth, pycoin, pyzmq(v2.2+), pycrypto, lockfile, python-bitcoinlib (see [this link](https://github.com/CzarcraftDLA/czarcraftd/blob/master/pip-requirements.txt) for exact working versions)
* Litecoind

# Installation

**NOTE: This section covers manual installation of czarcraftd. If you want more of
an automated approach to czarcraftd installation for Windows and Linux, see [this link](http://czarcraft.io/docs/build-system/).**

In order for czarcraftd to function, it must be able to communicate with a
running instance of Litecoind or Litecoin-Qt, which handles many Litecoin‐specific
matters on its behalf, including all wallet and private key management. For
such interoperability, Litecoind must be run with the following options:
`-txindex=1` `-server=1`. This may require the setting of a JSON‐RPC password,
which may be saved in Litecoind’s configuration file.

czarcraftd needs to know at least the JSON‐RPC password of the Litecoind with
which it is supposed to communicate. The simplest way to set this is to
include it in all command‐line invocations of czarcraftd, such as
`./czarcraftd.py --rpc-password=PASSWORD ACTION`. To make this and other
options persistent across czarcraftd sessions, one may store the desired
settings in a configuration file specific to czarcraftd.

Note that the syntaxes for the countpartyd and the Litecoind configuraion
files are not the same. A Litecoind configuration file looks like this:

	rpcuser=bitcoinrpc
	rpcpassword=PASSWORD
	testnet=1
	txindex=1
	server=1

However, a czarcraftd configuration file looks like this:

	[Default]
	bitcoind-rpc-password=PASSWORD

Note the change in hyphenation between `rpcpassword` and `rpc-password`.

If and only if czarcraftd is to be run on the Litecoin testnet, with the
`--testnet` CLI option, Litecoind must be set to do the same (`-testnet=1`).
czarcraftd may run with the `--testcoin` option on any blockchain,
however.

# Updating your requirements

Sometimes the underlying package requirements may change for `czarcraftd`. If you build and installed it from scratch,
you can manually update these requirements by executing something like:
```
    pip install --upgrade -r pip-requirements.txt 
```

# Test suite

The test suite is invoked with `py.test` in the root directory of the repository.
Litecoind testnet and mainnet must run on the default ports and use the same rpcuser and rpcpassword. 
Do not include the following values ​​in czarcraftd.conf: bitcoind-rpc-connect, bitcoind-rpc-port, rpc-host, rpc-port and testnet.

# Usage
The command‐line syntax of czarcraftd is generally that of
`./czarcraftd.py {OPTIONS} ACTION {ACTION-OPTIONS}`. There is a one action
per message type, which action produces and broadcasts such a message; the
message parameters are specified following the name of the message type. There
are also actions which do not correspond to message types, but rather exist to
provide information about the state of the Czarcraft network, e.g. current
balances or open orders.

For a summary of the command‐line arguments and options, see
`./czarcraftd.py --help`.

# Versioning
* Major version changes require a full rebuild of the database.
* Minor version changes require a database reparse.
* Most protocol changes are retroactive on testnet.

## Input and Output
* Quantities of divisible assets are written to eight decimal places.
* Quantities of indivisible assets are written as integers.
* All other quantities, i.e. prices, odds, leverages, feed values and target
values, fee multipliers, are specified to four decimal places.
* czarcraftd identifies an Order, Bet, Order Match or Bet Match by an
‘Order ID’, ‘Bet ID’, ‘Order Match ID’, or ‘Bet Match ID’, respectively. Match
IDs are concatenations of the hashes of the two transactions which compose the
corresponding Match, in the order of their appearances in the blockchain.


## Examples
The following examples are abridged for parsimony.

* Server

	The `server` command should always be running in the background. All other commands will fail if the index of the last block in the database is less than that of the last block seen by Litecoind.

* Burn

	`burn --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --quantity=.5`

* Send divisible or indivisible assets

	```
	send --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --quantity=3 --asset=BBBC
	--to=n3BrDB6zDiEPWEE6wLxywFb4Yp9ZY5fHM7
	```

* Buy LTC for DLA
	
	```
	order --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --get-quantity=10 --get-asset=LTC
	--give-quantity=20 --give-asset=DLA --expiration=10 --fee_required=.001
	```

* Buy BBBC for LTC

	```
	order --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --get-quantity=10 --get-asset=BBBC
	--give-quantity=20 --give-asset=LTC --expiration=10 --fee_provided=0.001
	```

* Buy DLA for BBBC
	```
	order --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --get-quantity=10 --get-asset=DLA
	--give-quantity=20 --give-asset=BBBC --expiration=10
	```

* LTCPay
	```
	ltcpay --source=-source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --order-match-id=092f15d36786136c4d868c33356ec3c9b5a0c77de54ed0e96a8dbdd8af160c23
	```

* Issue

	`issuance --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --quantity=100 --asset='BBBC'`

	`issuance --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --quantity=100 --asset='BBBQ' --divisible`

* Broadcast
	```
	broadcast --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --text="Litecoin price feed" --value=825.22
	--fee-multiplier=0.001
	```

	Note: for some users czarcraftd has trouble parsing spaces in the `--text` argument. One workaround is to
		add an additional set of quotes. For example, `--text='"Litecoin price feed"'`.

* Bet
	
	Equal/Not Equal Bet:
	
	Example: Bet on Super Bowl Feed. Denver vs. Seattle. Feed value of 1 means Seattle Wins. Feed value of 2 means 	        	Denver Wins. This command places a 1 DLA bet on the Super Bowl Feed for Seattle to win, paying out 2 to         	1. The bet will expire in 100 blocks and the settlement value of the bet is based on the first feed 	                update after the deadline timestamp of February 3, 2014 1:39 PM US Eastern Standard Time (UTC-0500)
	```
	bet --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --feed-address=n3BrDB6zDiEPWEE6wLxywFb4Yp9ZY5fH --bet-type=Equal
	--deadline=2014-02-03T13:39:00-0500 --wager=1 --counterwager=2 --target-value=1 --expiration=100
	```

	Contract for Difference:
	
	Example: Bet on Litecoin Price Feed. This command places a bearish (short) 1 DLA wager on the price of LTC/USD 				with 2X leverage. The bet will expire in 100 blocks and the settlement value of the bet is based 			on the first feed update after the deadline timestamp of February 3, 2014 1:39 PM US Eastern 					Standard Time (UTC-0500)
	```
	bet --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --feed-address=n3BrDB6zDiEPWEE6wLxywFb4Yp9ZY5fH --bet-type=BearCFD --deadline=2014-02-03T13:39:00-0500 --wager=1 --counterwager=1 --leverage=10080 --expiration=100
	```

* Rock-Paper-Scissors
	
	Open a Rock-Paper-Scissors like game with arbitrary possible moves (Must be an odd number greater or equal than 3). Until you make an rpsresolve transaction, your move is stored as an hash and keep secret.
	
	Example: Play rock-paper-scissors-spock-lizard (http://en.wikipedia.org/wiki/Rock-paper-scissors-lizard-Spock):

	```
	rps --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --possible-moves=5 --move=2 --wager=1 --expiration=100
	```

	Keep well the random number generated, you need it to resolve the game after matching:
	
	```
	rpsresolve --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --move=2 --random=adc5eadf9cb698ff6f2410d76131a4ee --rps-match-id=c68ffe144952977b94f8d7b49a1c7be7a4bb522c56f2ffc5aefa78ae0f9799b003b0f79d59ba660138583277b8267301a1030577790b945c4e8f845f19c23ca2
	```

* Cancel
	```
	cancel --source=-source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --offer-hash=092f15d36786136c4d868c33356ec3c9b5a0c77de54ed0e96a8dbdd8af160c23
	```

* Dividend
	```
	dividend --source=mtQheFaSfWELRB2MyMBaiWjdDm6ux9Ezns --quantity-per-share=1 --asset=MULTIPOOLSTOCK
	```

* Market

	The `market` action prints out tables of open orders, open bets, feeds, and order matches currently awaiting 	        Litecoin payments from one of your addresses. 
	
	It is capable of filtering orders by assets to be bought and sold.
	
	Example:
	
	To filter the market to only show offers to sell (give) LTC:
	```
	market --give-asset=LTC
	```
	
	To filter the market to only show offers to buy (get) LTC:
	```
	market --get-asset=LTC
	```
	
	To filter the market to only show offers to sell LTC for DLA:
	```
	market --give-asset=LTC --get-asset=DLA
	```

* Asset

	The `asset` action displays the basic properties of a given asset.

* Address

	The `address` action displays the details of of all transactions involving the Czarcraft address which is its argument.

