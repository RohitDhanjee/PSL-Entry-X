import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader } from 'lucide-react';

const OAuthCallback = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState(null);

  useEffect(() => {
    const handleCallback = () => {
      const params = new URLSearchParams(location.search);
      const token = params.get('token');
      const provider = params.get('provider');
      const errorMsg = params.get('error');

      if (errorMsg) {
        setError(decodeURIComponent(errorMsg));
        setTimeout(() => navigate('/auth'), 3000);
        return;
      }

      if (token) {
        if (window.opener) {
          window.opener.postMessage(
            {
              type: 'oauth-callback',
              token: token,
              provider: provider,
            },
            window.location.origin
          );
          window.close();
        } else {
          localStorage.setItem('token', token);
          navigate('/dashboard');
        }
      } else {
        setError('No token received from OAuth provider');
        setTimeout(() => navigate('/auth'), 3000);
      }
    };

    handleCallback();
  }, [location, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-purple-50 to-blue-50">
      <div className="text-center">
        {error ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md">
            <h2 className="text-xl font-bold text-red-800 mb-2">
              Authentication Failed
            </h2>
            <p className="text-red-600">{error}</p>
            <p className="text-sm text-gray-600 mt-4">
              Redirecting to login...
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow-lg p-8">
            <Loader className="w-12 h-12 text-purple-600 animate-spin mx-auto mb-4" />
            <h2 className="text-xl font-semibold text-gray-800 mb-2">
              Completing Sign In...
            </h2>
            <p className="text-gray-600">
              Please wait while we finish setting up your account.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default OAuthCallback;