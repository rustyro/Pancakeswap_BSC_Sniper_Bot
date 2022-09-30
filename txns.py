from hexbytes import HexBytes
from requests import ConnectionError
from web3 import Web3
from web3._utils.transactions import get_required_transaction
from web3.types import _Hash32
import json
from style import style
import sys

from decimal import *

# More than 8 Decimals are not supportet in the input from the token buy amount! No impact to Token Decimals!
getcontext().prec = 8


amount_keys = ["value", "gasPrice"]


def connect():
    with open("./settings.json") as f:
        keys = json.load(f)
    if keys["RPC"][:2].lower() == "ws":
        w3 = Web3(Web3.WebsocketProvider(keys["RPC"]))
    else:
        w3 = Web3(Web3.HTTPProvider(keys["RPC"]))
    return w3


w3 = connect()


def setup_token(token_address, _w3=w3):
    with open("./abis/bep20_abi_token.json") as f:
        contract_abi = json.load(f)
    token_contract = _w3.eth.contract(address=token_address, abi=contract_abi)
    return token_contract


class TXN:
    def __init__(self, token_address, quantity, show_value=True):
        self.w3 = w3
        self.address, self.private_key = self.setup_address()
        self.token_address = Web3.toChecksumAddress(token_address)
        self.token_contract = setup_token(self.token_address)
        self.swapper_address, self.swapper = self.setup_swapper()
        self.slippage = self.setupSlippage()
        self.quantity = quantity
        self.MaxGasInBNB, self.gas_price = self.setupGas()

    def connect(self):
        with open("./settings.json") as f:
            keys = json.load(f)
        if keys["RPC"][:2].lower() == "ws":
            w3 = Web3(Web3.WebsocketProvider(keys["RPC"]))
        else:
            w3 = Web3(Web3.HTTPProvider(keys["RPC"]))
        return w3

    def setupGas(self):
        with open("./settings.json") as f:
            keys = json.load(f)
        return keys['MaxTXFeeBNB'], int(keys['GWEI_GAS'] * (10 ** 9))

    def setup_address(self):
        with open("./settings.json") as f:
            keys = json.load(f)
        if len(keys["metamask_address"]) <= 41:
            print(style.RED + "Set your Address in the keys.json file!" + style.RESET)
            raise SystemExit
        if len(keys["metamask_private_key"]) <= 42:
            print(style.RED + "Set your PrivateKey in the keys.json file!" + style.RESET)
            raise SystemExit
        return keys["metamask_address"], keys["metamask_private_key"]

    def setupSlippage(self):
        with open("./settings.json") as f:
            keys = json.load(f)
        return keys['Slippage']

    def get_token_decimals(self):
        return self.token_contract.functions.decimals().call()

    def getBlockHigh(self):
        return self.w3.eth.block_number

    def setup_swapper(self):
        swapper_address = Web3.toChecksumAddress("0xdEdf20172b6dC39817026c125f52d4fad8E0f29b")
        with open("./abis/BSC_Swapper.json") as f:
            contract_abi = json.load(f)
        swapper = self.w3.eth.contract(address=swapper_address, abi=contract_abi)
        return swapper_address, swapper

    def setup_token(self):
        with open("./abis/bep20_abi_token.json") as f:
            contract_abi = json.load(f)
        token_contract = self.w3.eth.contract(address=self.token_address, abi=contract_abi)
        return token_contract

    def get_token_balance(self):
        return self.token_contract.functions.balanceOf(self.address).call() / (
                    10 ** self.token_contract.functions.decimals().call())
    def checkToken(self):
        tokenInfos = self.swapper.functions.getTokenInformations(self.token_address).call()
        buy_tax = round((tokenInfos[0] - tokenInfos[1]) / tokenInfos[0] * 100 ,2)
        sell_tax = round((tokenInfos[2] - tokenInfos[3]) / tokenInfos[2] * 100 ,2)
        if tokenInfos[5] and tokenInfos[6] == True:
            honeypot = False
        else:
            honeypot = True
        print(style.GREEN +"[TOKENTAX] Current Token BuyTax:",buy_tax ,"%" + style.RESET)
        print(style.GREEN +"[TOKENTAX] Current Token SellTax:",sell_tax ,"%" + style.RESET)
        return buy_tax, sell_tax, honeypot

    def checkifTokenBuyDisabled(self):
        disabled = self.swapper.functions.getTokenInformations(self.token_address).call()[
            4]  # True if Buy is enabled, False if Disabled.
        # todo: find a solution for bugged tokens that never can be buy.
        return disabled

    def estimateGas(self, txn):
        gas = self.w3.eth.estimateGas({
            "from": txn['from'],
            "to": txn['to'],
            "value": txn['value'],
            "data": txn['data']})
        gas = gas + (gas / 10)  # Adding 1/10 from gas to gas!
        maxGasBNB = Web3.fromWei(gas * self.gas_price, "ether")
        print(style.GREEN + "\nMax Transaction cost " + str(maxGasBNB) + " BNB" + style.RESET)

        if maxGasBNB > self.MaxGasInBNB:
            print(style.RED + "\nTx cost exceeds your settings, exiting!")
            raise SystemExit
        return gas

    def getOutputfromBNBtoToken(self):
        call = self.swapper.functions.getOutputfromETHtoToken(
            self.token_address,
            int(self.quantity * (10 ** 18)),
        ).call()
        Amount = call[0]
        Way = call[1]
        return Amount, Way

    def getOutputfromTokentoBNB(self, last_price=0):
        try:
            call = self.swapper.functions.getOutputfromTokentoETH(
                self.token_address,
                int(self.token_contract.functions.balanceOf(self.address).call()),
            ).call()
            Amount = call[0]
            Way = call[1]
            return Amount, Way
        except ConnectionError as e:
            print("Poor connection. Attempting to reconnect...")
            return last_price * (10 ** 18),

    def getLiquidityBNB(self):
        raw_call = self.swapper.functions.fetchLiquidityETH(self.token_address).call()
        real = raw_call / (10**18)
        return raw_call, real

    def buy_token(self):
        self.quantity = Decimal(self.quantity) * (10 ** 18)
        txn = self.swapper.functions.fromETHtoToken(
            self.address,
            self.token_address,
            self.slippage
        ).buildTransaction(
            {'from': self.address,
             'gas': 480000,
             'gasPrice': self.gas_price,
             'nonce': self.w3.eth.getTransactionCount(self.address),
             'value': int(self.quantity)}
        )
        txn.update({'gas': int(self.estimateGas(txn))})
        signed_txn = self.w3.eth.account.sign_transaction(
            txn,
            self.private_key
        )
        txn = self.w3.eth.sendRawTransaction(signed_txn.rawTransaction)
        print(style.GREEN + "\nBUY Hash:", txn.hex() + style.RESET)
        txn_receipt = self.w3.eth.waitForTransactionReceipt(txn)
        if txn_receipt["status"] == 1:
            return True, style.GREEN + "\nBUY Transaction Successfull!" + style.RESET, txn.hex()
        else:
            return False, style.RED + "\nBUY Transaction Faild!" + style.RESET

    def is_approve(self):
        Approve = self.token_contract.functions.allowance(self.address, self.swapper_address).call()
        Aproved_quantity = self.token_contract.functions.balanceOf(self.address).call()
        if int(Approve) <= int(Aproved_quantity):
            return False
        else:
            return True

    def approve(self):
        if self.is_approve() == False:
            txn = self.token_contract.functions.approve(
                self.swapper_address,
                115792089237316195423570985008687907853269984665640564039457584007913129639935  # Max Approve
            ).buildTransaction(
                {'from': self.address,
                 'gas': 100000,
                 'gasPrice': self.gas_price,
                 'nonce': self.w3.eth.getTransactionCount(self.address),
                 'value': 0}
            )
            txn.update({'gas': int(self.estimateGas(txn))})
            signed_txn = self.w3.eth.account.sign_transaction(
                txn,
                self.private_key
            )
            txn = self.w3.eth.sendRawTransaction(signed_txn.rawTransaction)
            print(style.GREEN + "\nApprove Hash:", txn.hex() + style.RESET)
            txn_receipt = self.w3.eth.waitForTransactionReceipt(txn)
            if txn_receipt["status"] == 1:
                return True, style.GREEN + "\nApprove Successfull!" + style.RESET
            else:
                return False, style.RED + "\nApprove Transaction Faild!" + style.RESET
        else:
            return True, style.GREEN + "\nAllready approved!" + style.RESET

    def sell_tokens(self):
        self.approve()
        txn = self.swapper.functions.fromTokentoETH(
            self.address,
            self.token_address,
            int(self.token_contract.functions.balanceOf(self.address).call()),
            self.slippage
        ).buildTransaction(
            {'from': self.address,
             'gas': 550000,
             'gasPrice': self.gas_price,
             'nonce': self.w3.eth.getTransactionCount(self.address),
             'value': 0}
        )
        txn.update({'gas': int(self.estimateGas(txn))})
        signed_txn = self.w3.eth.account.sign_transaction(
            txn,
            self.private_key
        )
        txn = self.w3.eth.sendRawTransaction(signed_txn.rawTransaction)
        print(style.GREEN + "\nSELL Hash :", txn.hex() + style.RESET)
        txn_receipt = self.w3.eth.waitForTransactionReceipt(txn)
        if txn_receipt["status"] == 1:
            return True, style.GREEN + "\nSELL Transaction Successfull!" + style.RESET, txn.hex()
        else:
            return False, style.RED + "\nSELL Transaction Faild!" + style.RESET

    @staticmethod
    def get_details(txhash: _Hash32) -> dict:
        """
        :param txhash: Hash of the transaction we need details of.
        :return: dict
        """

        res = dict(get_required_transaction(w3, txhash))
        for k, v in res.items():
            if k in amount_keys:
                res[k] = v / (10 ** 18)
            if isinstance(v, HexBytes):
                res[k] = v.hex()
        return res

    def get_value(self, txhash) -> float:

        dets = self.get_details(txhash)
        if not dets.get("value"):
            value = self.getOutputfromTokentoBNB()[0]
            dets["value"] = value / (10 ** 18)

        return int(self.token_contract.functions.balanceOf(self.address).call() - 1)
