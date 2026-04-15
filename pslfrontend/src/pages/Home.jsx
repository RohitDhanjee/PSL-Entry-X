import React, { useContext } from 'react'
import { Link } from 'react-router-dom';
import { Shield, Smartphone, QrCode, RefreshCcw } from 'lucide-react';
import { Button } from '@mui/material';
import AuthContext from '../context/AuthContext'

const Home = () => {
    const { isAuthenticated } = useContext(AuthContext);
  
  return (
    <div className="bg-white">
      {/* Hero Section */}
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-green-900 to-green-700 opacity-90"></div>
        <div 
          className="absolute inset-0 bg-cover bg-center opacity-20" 
          style={{ backgroundImage: "url('https://images.unsplash.com/photo-1540747913346-19e32dc3e97e?q=80&w=2805&auto=format&fit=crop')" }}
        ></div>
        <div className="relative max-w-7xl mx-auto py-24 px-4 sm:py-32 sm:px-6 lg:px-8">
          <h1 className="text-4xl font-extrabold tracking-tight text-white sm:text-5xl lg:text-6xl uppercase">
            PSL Entry X
          </h1>
          <p className="mt-6 max-w-2xl text-xl text-green-100 font-medium">
            Next-generation stadium entry powered by blockchain. Beat the scalpers, prevent screenshot fraud, and experience seamless gating with dynamic QR codes.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row gap-4">
            <Link to={!isAuthenticated ? "/auth" : "/dashboard"}>
              <Button variant="contained" color='success' size="large" className='!p-4 !font-bold'>
                {!isAuthenticated ? 'Fan Login / Register' : 'Open PSL Entry X'}
              </Button>
            </Link>
          </div>
        </div>
      </div>

      {/* Features */}
      <div className="py-16 bg-gray-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center">
            <h2 className="text-base font-bold text-green-800 tracking-wide uppercase">Core Features</h2>
            <p className="mt-1 text-3xl font-extrabold text-gray-900 sm:text-4xl">
              Ticket Security Redefined
            </p>
            <p className="max-w-xl mt-5 mx-auto text-lg text-gray-500">
              We leverage blockchain ownership and dynamic cryptography to make fraud impossible.
            </p>
          </div>

          <div className="mt-16">
            <div className="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
              <div className="pt-6">
                <div className="flow-root bg-white rounded-lg shadow-lg px-6 pb-8 h-full">
                  <div className="-mt-6">
                    <div>
                      <span className="inline-flex items-center justify-center p-3 bg-green-800 rounded-md shadow-lg">
                        <QrCode className="h-6 w-6 text-white" aria-hidden="true" />
                      </span>
                    </div>
                    <h3 className="mt-8 text-lg font-bold text-gray-900 tracking-tight">Dynamic QR Entry</h3>
                    <p className="mt-5 text-base text-gray-500">
                      QR codes refresh every 60 seconds, rendering static screenshots completely useless at the gate.
                    </p>
                  </div>
                </div>
              </div>

              <div className="pt-6">
                <div className="flow-root bg-white rounded-lg shadow-lg px-6 pb-8 h-full">
                  <div className="-mt-6">
                    <div>
                      <span className="inline-flex items-center justify-center p-3 bg-blue-600 rounded-md shadow-lg">
                        <Shield className="h-6 w-6 text-white" aria-hidden="true" />
                      </span>
                    </div>
                    <h3 className="mt-8 text-lg font-bold text-gray-900 tracking-tight">Anti-Scalping Protocol</h3>
                    <p className="mt-5 text-base text-gray-500">
                      Smart contract rules cap resale prices at 150%, protecting real fans from predatory secondary markets.
                    </p>
                  </div>
                </div>
              </div>

              <div className="pt-6">
                <div className="flow-root bg-white rounded-lg shadow-lg px-6 pb-8 h-full">
                  <div className="-mt-6">
                    <div>
                      <span className="inline-flex items-center justify-center p-3 bg-purple-600 rounded-md shadow-lg">
                        <RefreshCcw className="h-6 w-6 text-white" aria-hidden="true" />
                      </span>
                    </div>
                    <h3 className="mt-8 text-lg font-bold text-gray-900 tracking-tight">P2P Transfers</h3>
                    <p className="mt-5 text-base text-gray-500">
                      Safely transfer tickets to friends or resell them instantly. Blockchain settles the ownership natively.
                    </p>
                  </div>
                </div>
              </div>

              <div className="pt-6">
                <div className="flow-root bg-white rounded-lg shadow-lg px-6 pb-8 h-full">
                  <div className="-mt-6">
                    <div>
                      <span className="inline-flex items-center justify-center p-3 bg-amber-500 rounded-md shadow-lg">
                        <Smartphone className="h-6 w-6 text-white" aria-hidden="true" />
                      </span>
                    </div>
                    <h3 className="mt-8 text-lg font-bold text-gray-900 tracking-tight">Live Gate Scanning</h3>
                    <p className="mt-5 text-base text-gray-500">
                      Offline-first resilient scanning allows stadium staff to validate entry in milliseconds.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Home;
