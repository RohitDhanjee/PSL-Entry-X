import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Mail, Lock, ArrowLeft } from 'lucide-react';
import { Button, TextField, InputAdornment, Input } from '@mui/material';
import { baseURL } from '../../utils/backend_url';
import axios from 'axios';

const ForgotPasswordForm = ({ onBack }) => {
  const [step, setStep] = useState('email');
  const [email, setEmail] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const navigate = useNavigate();

  // Step 1: Send email
  const handleSubmitEmail = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await axios.post(`${baseURL}/api/v1/auth/forgot-password`, {
        email: email,   // ✅ send as JSON body
      });

      console.log("Successfully sent code!");
      setStep('verify');
    } catch (err) {
      setError(err.response?.data?.detail || "Something went wrong");
      console.log(err.response?.data || err);
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Verify + Reset Password
const handleVerifyCode = async (e) => {
  e.preventDefault();
  setError(null);

  if (newPassword !== confirmPassword) {
    setError('Passwords do not match');
    return;
  }
  setLoading(true);

try {
  await axios.post(`${baseURL}/api/v1/auth/reset-password`, {
    email: email,
    otp: verificationCode,
    new_password: newPassword,
  });

  console.log("Password reset success");

  // ✅ Success ke baad error clear + form reset
  setError(null);
  setStep("done");

  // ✅ Chhota sa delay aur navigate
  setTimeout(() => {
    navigate("/auth"); // redirect to login
  }, 500);

} catch (err) {
  setError(err.response?.data?.detail || "Invalid code or server error");
  console.log(err.response?.data || err);
} finally {
  setLoading(false);
}

};


  return (
    <div className="bg-white p-8 rounded-2xl shadow-lg w-full max-w-xl">
      <div className="max-w-md w-full space-y-8">
        <div>
          <p onClick={onBack} className="flex items-center text-lg text-emerald-700 hover:text-emerald-600 cursor-pointer">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back to Login
          </p>
          <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
            {step === 'email' && 'Reset your password'}
            {step === 'verify' && 'Enter verification code'}
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600">
            {step === 'email' && 'Enter your email address to receive a verification code'}
            {step === 'verify' && 'We sent a code to your email'}
          </p>
        </div>

        <div className="mt-8 bg-white py-8 px-4 shadow rounded-lg sm:px-10">
          {error && (
            <div className="mb-4 bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-md text-sm">
              {error}
            </div>
          )}

          {/* Step 1: Email */}
          {step === 'email' && (
            <form className="space-y-6" onSubmit={handleSubmitEmail}>
              <TextField
                label="Email address"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                fullWidth
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Mail style={{ color: 'gray' }} />
                    </InputAdornment>
                  ),
                }}
              />
              <Button
                type="submit"
                color="success"
                variant='contained'
                disabled={loading}
                fullWidth
                className='!my-5'
              >
                {loading ? "Sending..." : "Send Verification Code"}
              </Button>
            </form>
          )}

          {/* Step 2: Verify + Reset */}
          {step === 'verify' && (
            <form className="space-y-6" onSubmit={handleVerifyCode}>
              <Input
                placeholder="Verification Code"
                type="text"
                value={verificationCode}
                onChange={(e) => setVerificationCode(e.target.value)}
                required
                fullWidth
              />
              <Input
                placeholder="New Password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                fullWidth
              />
              <Input
                placeholder="Confirm Password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                fullWidth
              />
              <Button
                type="submit"
                color="success"
                variant='contained'
                disabled={loading}
                fullWidth
                className='!my-5'
              >
                {loading ? "Resetting..." : "Reset Password"}
              </Button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default ForgotPasswordForm;
