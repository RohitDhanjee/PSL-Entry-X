import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class Web3AvailabilityChecker:
    @staticmethod
    async def check_web3_availability(user_wallet: str = None) -> Dict[str, Any]:
        from services.web3_service import web3_service
        
        try:
            if not web3_service or not web3_service.w3:
                return {
                    'available': False,
                    'reason': 'web3_service_unavailable',
                    'fallback': 'paypal',
                    'message': 'Blockchain service temporarily unavailable'
                }
            
            if getattr(web3_service, 'demo_mode', False):
                return {
                    'available': True,
                    'demo_mode': True,
                    'fallback': 'none',
                    'message': 'Running in demo mode'
                }
            
            if user_wallet:
                try:
                    balance_wei = web3_service.w3.eth.get_balance(user_wallet)
                    balance_eth = web3_service.w3.from_wei(balance_wei, 'ether')
                    
                    if balance_eth < 0.001:
                        return {
                            'available': False,
                            'reason': 'insufficient_balance',
                            'fallback': 'paypal',
                            'message': f'Insufficient ETH balance: {balance_eth:.6f} ETH',
                            'balance_eth': float(balance_eth)
                        }
                    
                    return {
                        'available': True,
                        'fallback': 'none',
                        'balance_eth': float(balance_eth),
                        'message': 'Web3 available and user has sufficient balance'
                    }
                    
                except Exception as e:
                    logger.warning(f"Wallet balance check failed: {e}")
                    return {
                        'available': False,
                        'reason': 'wallet_error',
                        'fallback': 'paypal',
                        'message': f'Wallet error: {str(e)}'
                    }
            
            return {
                'available': False,
                'reason': 'no_wallet',
                'fallback': 'paypal',
                'message': 'No wallet address connected'
            }
            
        except Exception as e:
            logger.error(f"Web3 availability check failed: {e}")
            return {
                'available': False,
                'reason': 'check_failed',
                'fallback': 'paypal',
                'message': f'Web3 availability check failed: {str(e)}'
            }

web3_checker = Web3AvailabilityChecker()