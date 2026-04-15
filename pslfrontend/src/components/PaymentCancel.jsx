import React, { useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { XCircle, ArrowLeft } from 'lucide-react';
import toast from 'react-hot-toast';

const PaymentCancel = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const hasShownToast = useRef(false); // ✅ Prevent duplicate toast

  useEffect(() => {
    // ✅ Check if already shown
    if (hasShownToast.current) {
      return;
    }
    
    // ✅ Mark as shown
    hasShownToast.current = true;
    
    // Show cancellation message only once
    toast.error('Payment was cancelled', {
      duration: 4000,
    });
  }, []); // ✅ Empty dependency array - only run once on mount

  // Get type from URL to determine where to redirect
  const type = searchParams.get('type');
  const tokenId = searchParams.get('token_id') || searchParams.get('token'); // ✅ Also check 'token' param

  const handleGoBack = () => {
    // Navigate back based on type or default to dashboard
    switch (type) {
      case 'registration':
        navigate('/dashboard/upload');
        break;
      case 'ticket':
        if (tokenId) {
          navigate(`/ticket/${tokenId}`);
        } else {
          navigate('/explorer');
        }
        break;
      default:
        navigate('/dashboard');
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="max-w-md w-full bg-white rounded-lg shadow-md p-8 text-center">
        <div className="flex justify-center mb-6">
          <XCircle className="w-16 h-16 text-orange-500" />
        </div>
        <h2 className="text-2xl font-bold text-gray-900 mb-4">
          Payment Cancelled
        </h2>
        <p className="text-gray-600 mb-6">
          You cancelled the PayPal payment process. No charges were made to your account.
        </p>
        <div className="space-y-3">
          <button
            onClick={handleGoBack}
            className="w-full px-4 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-semibold transition-colors flex items-center justify-center gap-2"
          >
            <ArrowLeft className="w-5 h-5 text-white" />
            <span className="text-white">Go Back</span>
          </button>
          <button
            onClick={() => navigate('/dashboard')}
            className="w-full px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 font-semibold transition-colors"
          >
            Go to Dashboard
          </button>
        </div>
        <p className="mt-4 text-sm text-gray-500">
          If you want to complete the payment, you can try again from the previous page.
        </p>
      </div>
    </div>
  );
};

export default PaymentCancel;