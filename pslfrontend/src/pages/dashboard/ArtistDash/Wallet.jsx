import React, { useEffect, useState } from 'react';
import { DollarSign, ArrowRight, CreditCard, Wallet, TrendingUp, Clock, ArrowUpRight } from 'lucide-react';
import { Badge, Card, Button } from '@mui/material';
import { useWeb3 } from '../../../context/Web3Context';
import { useAuth } from '../../../context/AuthContext';
import { transactionsAPI, ticketsAPI } from '../../../services/api';
import { UserIdentifier, CurrencyConverter } from '../../../utils/currencyUtils';
import LoadingSpinner from '../../../components/common/LoadingSpinner';
import toast from 'react-hot-toast';

const Wallets = () => {
  const { account, isCorrectNetwork, balance, selectedNetwork, explorerUrl } = useWeb3();
  const { isAuthenticated, isWalletConnected, user } = useAuth();

  const [isLoading, setIsLoading] = useState(true);
  const [transactions, setTransactions] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [royaltyEarnings, setRoyaltyEarnings] = useState('0.0000');
  const [error, setError] = useState(null);
  const [isWithdrawing, setIsWithdrawing] = useState(false);

  // Get user identifier for API calls
  const userIdentifier = UserIdentifier.getUserIdentifier(user);

  // Fetch transactions and tickets
  useEffect(() => {
    if (!isAuthenticated || !userIdentifier) return;

    const fetchData = async () => {
      setIsLoading(true);
      setError(null);
      
      try {
        console.log(`🔄 Fetching royalty data for user: ${userIdentifier}`);

        // Fetch all data in parallel
        const [txsRes, artsRes, earningsRes] = await Promise.allSettled([
          transactionsAPI.getByUser(userIdentifier),
          ticketsAPI.getByCreator(userIdentifier),
          transactionsAPI.getByUser(userIdentifier, { type: 'ROYALTY' })
        ]);

        // Handle transactions
        if (txsRes.status === 'fulfilled') {
          setTransactions(txsRes.value.data || []);
        } else {
          console.warn('Transactions fetch failed:', txsRes.reason);
          setTransactions([]);
        }

        // Handle tickets
        if (artsRes.status === 'fulfilled') {
          setTickets(artsRes.value.data || []);
        } else {
          console.warn('Tickets fetch failed:', artsRes.reason);
          setArtworks([]);
        }

        // Handle royalty earnings
        if (earningsRes.status === 'fulfilled') {
          const royaltyTransactions = earningsRes.value.data || [];
          const total = royaltyTransactions.reduce((sum, tx) => {
            const value = parseFloat(tx?.value || 0);
            return sum + (isNaN(value) ? 0 : value);
          }, 0);
          setRoyaltyEarnings(total.toFixed(4));
        } else {
          console.warn('Royalty transactions fetch failed:', earningsRes.reason);
          setRoyaltyEarnings('0.0000');
        }
        
      } catch (error) {
        console.error('❌ Error fetching royalty data:', error);
        setError(`Failed to load royalty data: ${error.message}`);
        toast.error('Failed to load royalty data');
        
        setTransactions([]);
        setArtworks([]);
        setRoyaltyEarnings('0.0000');
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [isAuthenticated, userIdentifier]);

  const handleWithdraw = () => {
    setIsWithdrawing(true);
    // Simulate withdrawal process
    setTimeout(() => {
      setIsWithdrawing(false);
      toast.success('Withdrawal request submitted successfully!');
    }, 2000);
  };

  // Format address helper
  const formatAddress = (address) => {
    if (!address || typeof address !== 'string') return 'Invalid address';
    return `${address.substring(0, 6)}...${address.substring(address.length - 4)}`;
  };

  // Format transaction type for display
  const formatTransactionType = (type) => {
    return type?.replace('_', ' ') || 'Unknown';
  };

  // Format amount with currency
  const formatAmount = (tx) => {
    const amount = tx.value || '0';
    if (tx.payment_method === 'paypal') {
      const usdAmount = CurrencyConverter.ethToUsd(amount);
      return CurrencyConverter.formatUsd(usdAmount);
    }
    return CurrencyConverter.formatCrypto(amount, tx.network);
  };

  // ✅ Remove blocking - users can view wallet page with any payment method
  // Show wallet section if user has wallet, show PayPal section if user has PayPal

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Wallet & Royalties</h1>
        <p className="mt-1 text-sm text-gray-500">
          Manage your earnings and withdraw funds
        </p>
        <p className="mt-1 text-xs text-gray-400">
          User: {userIdentifier} (Methods: {UserIdentifier.getAvailablePaymentMethods(user).join(', ') || 'None'})
        </p>
      </div>

      {/* Error Display */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Balance and Stats Cards */}
        <div className="lg:col-span-2">
          {/* Stats Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <Card className="p-4">
              <div className="flex items-center">
                <div className="p-3 rounded-full bg-green-100 mr-4">
                  <TrendingUp className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-500">Total Royalties</p>
                  <p className="text-xl font-semibold text-gray-900">
                    {isLoading ? '...' : CurrencyConverter.formatCrypto(royaltyEarnings, selectedNetwork)}
                  </p>
                </div>
              </div>
            </Card>

            <Card className="p-4">
              <div className="flex items-center">
                <div className="p-3 rounded-full bg-blue-100 mr-4">
                  <Clock className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-500">Tickets</p>
                  <p className="text-xl font-semibold text-gray-900">
                    {isLoading ? '...' : tickets.length}
                  </p>
                </div>
              </div>
            </Card>

            <Card className="p-4">
              <div className="flex items-center">
                <div className="p-3 rounded-full bg-purple-100 mr-4">
                  <DollarSign className="w-5 h-5 text-purple-600" />
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-500">Transactions</p>
                  <p className="text-xl font-semibold text-gray-900">
                    {isLoading ? '...' : transactions.length}
                  </p>
                </div>
              </div>
            </Card>
          </div>

          {/* Balance Card */}
          <Card className="mb-6">
            <div className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-medium text-gray-900">Available Balance</h2>
                  <p className="mt-1 text-sm text-gray-500">Ready to withdraw</p>
                </div>
                <div className="text-3xl font-bold text-gray-900">
                  {isLoading ? '...' : CurrencyConverter.formatCrypto(royaltyEarnings, selectedNetwork)}
                </div>
              </div>
              <div className="mt-6">
                <Button
                  variant="contained"
                  color="secondary"
                  onClick={handleWithdraw}
                  disabled={isWithdrawing || parseFloat(royaltyEarnings) <= 0}
                  startIcon={<DollarSign className="h-5 w-5" />}
                >
                  {isWithdrawing ? 'Processing...' : 'Withdraw Funds'}
                </Button>
              </div>
            </div>
          </Card>

          {/* Transaction History */}
          <Card>
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-medium text-gray-900">Transaction History</h3>
            </div>
            
            {isLoading ? (
              <div className="flex justify-center p-12">
                <LoadingSpinner size="medium" />
              </div>
            ) : transactions.length === 0 ? (
              <div className="text-center p-12">
                <Clock className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">No transactions yet</h3>
                <p className="text-gray-500">
                  Once you register tickets or receive royalties, they'll appear here.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-gray-200">
                {transactions.map((tx) => (
                  <div key={tx.tx_hash || tx.id} className="px-6 py-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center">
                        <div className={`
                          p-2 rounded-full 
                          ${tx.transaction_type === 'ROYALTY' ? 'bg-green-100' : 
                            tx.transaction_type === 'SALE' ? 'bg-blue-100' : 
                            'bg-gray-100'}
                        `}>
                          {tx.transaction_type === 'ROYALTY' ? (
                            <TrendingUp className={`h-5 w-5 text-green-600`} />
                          ) : tx.transaction_type === 'SALE' ? (
                            <DollarSign className="h-5 w-5 text-blue-600" />
                          ) : (
                            <CreditCard className="h-5 w-5 text-gray-600" />
                          )}
                        </div>
                        <div className="ml-4">
                          <p className="text-sm font-medium text-gray-900">
                            {formatTransactionType(tx.transaction_type)}
                            {tx.metadata?.token_id && ` - Ticket #${tx.metadata.token_id}`}
                          </p>
                          <p className="text-sm text-gray-500">
                            {tx.created_at ? new Date(tx.created_at).toLocaleDateString() : 'N/A'}
                            {tx.payment_method && (
                              <span className={`ml-2 px-2 py-1 text-xs rounded-full ${
                                tx.payment_method === 'paypal' 
                                  ? 'bg-yellow-100 text-yellow-800' 
                                  : 'bg-blue-100 text-blue-800'
                              }`}>
                                {tx.payment_method}
                              </span>
                            )}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center">
                        <span className={`text-sm font-medium ${
                          tx.transaction_type === 'ROYALTY' ? 'text-green-600' : 
                          tx.value && parseFloat(tx.value) > 0 ? 'text-blue-600' : 'text-gray-500'
                        }`}>
                          {formatAmount(tx)}
                        </span>
                        {tx.tx_hash && (
                          <a 
                            href={`${explorerUrl}/tx/${tx.tx_hash}`} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="ml-3 text-purple-600 hover:text-purple-800"
                            title="View on Explorer"
                          >
                            <ArrowUpRight className="w-4 h-4" />
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Payment Methods and Info */}
        <div>
          {/* Payment Methods */}
          <Card className="mb-6">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-medium text-gray-900">Payment Methods</h3>
            </div>
            <div className="p-6">
              {UserIdentifier.hasWalletAddress(user) && (
                <div className="mb-6">
                  <h4 className="text-sm font-medium text-gray-900 mb-2">Connected Wallet</h4>
                  <div className="flex items-center p-4 bg-gray-50 rounded-lg">
                    <Wallet className="h-5 w-5 text-gray-400" />
                    <div className="ml-3">
                      <p className="text-sm font-medium text-gray-900">
                        {account ? formatAddress(account) : 'Not connected'}
                      </p>
                      <p className="text-xs text-gray-500">Ethereum</p>
                      {balance && (
                        <p className="text-xs text-green-600 mt-1">
                          Balance: {CurrencyConverter.formatCrypto(balance, selectedNetwork)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {UserIdentifier.hasPaymentMethod(user, "paypal") && (
                <div className="mb-6">
                  <h4 className="text-sm font-medium text-gray-900 mb-2">PayPal Account</h4>
                  <div className="flex items-center p-4 bg-yellow-50 rounded-lg">
                    <CreditCard className="h-5 w-5 text-yellow-600" />
                    <div className="ml-3">
                      <p className="text-sm font-medium text-gray-900">
                        Connected PayPal Account
                      </p>
                      <p className="text-xs text-gray-500">PayPal</p>
                    </div>
                  </div>
                </div>
              )}

              <div>
                <h4 className="text-sm font-medium text-gray-900 mb-2">Bank Account</h4>
                <div className="flex items-center p-4 bg-gray-50 rounded-lg">
                  <CreditCard className="h-5 w-5 text-gray-400" />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-gray-900">
                      •••• •••• •••• 4242
                    </p>
                    <p className="text-xs text-gray-500">Connected Bank Account</p>
                  </div>
                </div>
              </div>

              <div className="mt-6">
                <Button
                  variant="outlined"
                  fullWidth
                  color="secondary"
                >
                  Add Payment Method
                </Button>
              </div>
            </div>
          </Card>

          {/* Royalty Information */}
          <Card>
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="text-lg font-medium text-gray-900">How Royalties Work</h3>
            </div>
            <div className="p-6">
              <div className="space-y-3 text-sm text-gray-600">
                <div className="flex items-start">
                  <TrendingUp className="w-4 h-4 text-blue-600 mt-0.5 mr-2 flex-shrink-0" />
                  <span>Earn automatic royalties on every resale of your ticket</span>
                </div>
                <div className="flex items-start">
                  <DollarSign className="w-4 h-4 text-blue-600 mt-0.5 mr-2 flex-shrink-0" />
                  <span>Set your royalty percentage when registering ticket (up to 20%)</span>
                </div>
                <div className="flex items-start">
                  <Clock className="w-4 h-4 text-blue-600 mt-0.5 mr-2 flex-shrink-0" />
                  <span>Royalties are paid instantly and recorded on blockchain</span>
                </div>
                <div className="flex items-start">
                  <CreditCard className="w-4 h-4 text-blue-600 mt-0.5 mr-2 flex-shrink-0" />
                  <span>Withdraw your earnings to your bank account or keep in wallet</span>
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default Wallets;