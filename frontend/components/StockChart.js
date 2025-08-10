import { useState, useEffect } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart
} from 'recharts'
import { Box, Text, useColorModeValue } from '@chakra-ui/react'

// Mock data generator for demonstration
const generateMockData = (symbol) => {
  const basePrice = Math.random() * 1000 + 100 // Random base price between 100-1100
  const data = []
  const days = 30 // Last 30 days
  
  for (let i = days; i >= 0; i--) {
    const date = new Date()
    date.setDate(date.getDate() - i)
    
    // Generate somewhat realistic price movement
    const change = (Math.random() - 0.5) * 20 // Random change between -10 to +10
    const price = basePrice + (Math.sin(i / 5) * 50) + change
    
    data.push({
      date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      price: Math.max(price, 10), // Ensure price doesn't go below 10
      volume: Math.floor(Math.random() * 1000000) + 100000
    })
  }
  
  return data
}

const CustomTooltip = ({ active, payload, label }) => {
  const tooltipBg = useColorModeValue('white', 'gray.700')
  const tooltipBorder = useColorModeValue('gray.200', 'gray.600')
  
  if (active && payload && payload.length) {
    return (
      <Box
        bg={tooltipBg}
        border="1px solid"
        borderColor={tooltipBorder}
        borderRadius="md"
        p={3}
        shadow="lg"
      >
        <Text fontSize="sm" fontWeight="medium" mb={1}>
          {label}
        </Text>
        <Text fontSize="sm" color="blue.500">
          Price: ₹{payload[0].value.toLocaleString()}
        </Text>
        {payload[1] && (
          <Text fontSize="sm" color="gray.500">
            Volume: {payload[1].value.toLocaleString()}
          </Text>
        )}
      </Box>
    )
  }
  
  return null
}

export default function StockChart({ symbol, type = 'line' }) {
  const [chartData, setChartData] = useState([])
  const [loading, setLoading] = useState(true)
  
  const gridColor = useColorModeValue('#f0f0f0', '#374151')
  const textColor = useColorModeValue('#4a5568', '#a0a0a0')
  const lineColor = useColorModeValue('#3182ce', '#63b3ed')
  
  useEffect(() => {
    // In a real implementation, you would fetch actual historical data here
    // For now, we'll generate mock data
    const mockData = generateMockData(symbol)
    setChartData(mockData)
    setLoading(false)
  }, [symbol])
  
  if (loading) {
    return (
      <Box 
        h="100%" 
        display="flex" 
        alignItems="center" 
        justifyContent="center"
      >
        <Text color={textColor}>Loading chart...</Text>
      </Box>
    )
  }
  
  if (type === 'area') {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <defs>
            <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={lineColor} stopOpacity={0.8}/>
              <stop offset="95%" stopColor={lineColor} stopOpacity={0.1}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
          <XAxis 
            dataKey="date" 
            tick={{ fontSize: 12, fill: textColor }}
            axisLine={{ stroke: gridColor }}
          />
          <YAxis 
            tick={{ fontSize: 12, fill: textColor }}
            axisLine={{ stroke: gridColor }}
            tickFormatter={(value) => `₹${value.toFixed(0)}`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="price"
            stroke={lineColor}
            strokeWidth={2}
            fillOpacity={1}
            fill="url(#colorPrice)"
          />
        </AreaChart>
      </ResponsiveContainer>
    )
  }
  
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
        <XAxis 
          dataKey="date" 
          tick={{ fontSize: 12, fill: textColor }}
          axisLine={{ stroke: gridColor }}
        />
        <YAxis 
          tick={{ fontSize: 12, fill: textColor }}
          axisLine={{ stroke: gridColor }}
          tickFormatter={(value) => `₹${value.toFixed(0)}`}
        />
        <Tooltip content={<CustomTooltip />} />
        <Line
          type="monotone"
          dataKey="price"
          stroke={lineColor}
          strokeWidth={2}
          dot={{ fill: lineColor, strokeWidth: 2, r: 4 }}
          activeDot={{ r: 6, stroke: lineColor, strokeWidth: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
