import React from 'react'
import AppRoutes from './routes/Approutes'
import { Toaster } from "react-hot-toast";

const App = () => {
  return (
    <>
      <AppRoutes />
      <Toaster position="top-right" reverseOrder={false} />
    </>
  )
}
export default App;