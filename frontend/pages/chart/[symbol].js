import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'
import {
  Box,
  Container,
  Heading,
  VStack,
  HStack,
  Button,
  ButtonGroup,
  Text,
  Badge,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Alert,
  AlertIcon,
  Spinner,
  Card,
  CardBody,
  useColorModeValue
} from '@chakra-ui/react'
import { ArrowBackIcon } from '@chakra-ui/icons'
import { FaChartLine, FaChartArea, FaChartBar } from 'react-icons/fa'
import StockChart from '../../components/StockChart'
import axios from 'axios'

export default function ChartPage() {
  const router = useRouter()
  const { symbol } = router.query
  const [stockData, setStockData] = useState(null)
  const [chartType, setChartType] = useState('line')
  const [timeframe, setTimeframe] = useState('1M')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  const cardBg = useColorModeValue('white', 'gray.800')
  const borderColor = useColorModeValue('gray.200', 'gray.600')

  useEffect(() => {
    if (symbol) {
      fetchStockData()
    }
  }, [symbol])

  const fetchStockData = async () => {
    try {
      setLoading(true)
      setError(null)

      // Fetch stock prices to find the stock name and data
      const response = await axios.get('http://localhost:5000/api/prices')
      const stockName = Object.keys(response.data.prices).find(
        name => response.data.prices[name].symbol === symbol
      )
      
      if (stockName) {
        setStockData({
          name: stockName,
          ...response.data.prices[stockName]
        })
      } else {
        throw new Error('Stock symbol not found')
      }
    } catch (err) {
      setError('Failed to fetch stock data')
      console.error('Error fetching stock data:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <Box minH="100vh" bg="gray.900" p={6}>
        <Container maxW="container.xl">
          <VStack spacing={8}>
            <Spinner size="xl" color="blue.500" thickness="4px" />
            <Text color="gray.400">Loading chart data...</Text>
          </VStack>
        </Container>
      </Box>
    )
  }

  if (error || !stockData) {
    return (
      <Box minH="100vh" bg="gray.900" p={6}>
        <Container maxW="container.xl">
          <VStack spacing={6}>
            <Alert status="error" borderRadius="lg" maxW="md">
              <AlertIcon />
              <Text>{error || 'Stock not found'}</Text>
            </Alert>
            <Button
              leftIcon={<ArrowBackIcon />}
              onClick={() => window.close()}
              colorScheme="blue"
            >
              Close Window
            </Button>
          </VStack>
        </Container>
      </Box>
    )
  }

  const isPositive = stockData.change >= 0
  const changeColor = isPositive ? 'green.400' : 'red.400'

  return (
    <Box minH="100vh" bg="gray.900" p={6}>
      <Container maxW="container.xl">
        <VStack spacing={6} align="stretch">
          {/* Header */}
          <HStack justify="space-between" align="center">
            <VStack align="start" spacing={2}>
              <HStack spacing={3}>
                <Heading size="xl" color="white">
                  {stockData.name}
                </Heading>
                <Badge colorScheme="blue" variant="solid" borderRadius="full" px={3} py={1}>
                  {symbol}
                </Badge>
              </HStack>
              
              <HStack spacing={6}>
                <Stat>
                  <StatNumber color="white" fontSize="2xl">
                    ₹{stockData.price?.toLocaleString()}
                  </StatNumber>
                  <StatHelpText color={changeColor} fontSize="lg" m={0}>
                    {isPositive ? '+' : ''}₹{stockData.change} ({isPositive ? '+' : ''}{stockData.changePercent}%)
                  </StatHelpText>
                </Stat>
              </HStack>
            </VStack>
            
            <VStack spacing={3}>
              <Button
                leftIcon={<ArrowBackIcon />}
                variant="ghost"
                colorScheme="gray"
                onClick={() => window.close()}
                size="sm"
              >
                Close
              </Button>
              
              <Button
                colorScheme="blue"
                size="sm"
                onClick={() => {
                  const tradingSymbol = symbol.replace('.NS', '')
                  const tradingViewUrl = `https://www.tradingview.com/chart/?symbol=NSE%3A${tradingSymbol}&interval=1D`
                  window.open(tradingViewUrl, '_blank')
                }}
              >
                TradingView
              </Button>
            </VStack>
          </HStack>

          {/* Chart Controls */}
          <Card bg={cardBg} borderColor={borderColor}>
            <CardBody>
              <HStack justify="space-between" align="center" flexWrap="wrap" gap={4}>
                {/* Chart Type Selector */}
                <VStack align="start" spacing={2}>
                  <Text fontSize="sm" fontWeight="medium" color={useColorModeValue('gray.600', 'gray.300')}>
                    Chart Type
                  </Text>
                  <ButtonGroup size="sm" variant="outline">
                    <Button
                      leftIcon={<FaChartLine />}
                      colorScheme={chartType === 'line' ? 'blue' : 'gray'}
                      onClick={() => setChartType('line')}
                    >
                      Line
                    </Button>
                    <Button
                      leftIcon={<FaChartArea />}
                      colorScheme={chartType === 'area' ? 'blue' : 'gray'}
                      onClick={() => setChartType('area')}
                    >
                      Area
                    </Button>
                  </ButtonGroup>
                </VStack>

                {/* Timeframe Selector */}
                <VStack align="start" spacing={2}>
                  <Text fontSize="sm" fontWeight="medium" color={useColorModeValue('gray.600', 'gray.300')}>
                    Timeframe
                  </Text>
                  <ButtonGroup size="sm" variant="outline">
                    {['1D', '1W', '1M', '3M', '6M', '1Y'].map((tf) => (
                      <Button
                        key={tf}
                        colorScheme={timeframe === tf ? 'blue' : 'gray'}
                        onClick={() => setTimeframe(tf)}
                      >
                        {tf}
                      </Button>
                    ))}
                  </ButtonGroup>
                </VStack>
              </HStack>
            </CardBody>
          </Card>

          {/* Main Chart */}
          <Card bg={cardBg} borderColor={borderColor}>
            <CardBody>
              <Box h="500px" w="100%">
                <StockChart symbol={symbol} type={chartType} timeframe={timeframe} />
              </Box>
            </CardBody>
          </Card>

          {/* Chart Info */}
          <Card bg={cardBg} borderColor={borderColor}>
            <CardBody>
              <VStack spacing={4} align="stretch">
                <Heading size="md" color={useColorModeValue('gray.800', 'white')}>
                  Chart Information
                </Heading>
                
                <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.400')}>
                  This chart displays mock price data for demonstration purposes. 
                  In a production environment, this would be connected to real market data feeds.
                </Text>
                
                <HStack justify="space-between">
                  <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.400')}>
                    Data Source: Mock Data Generator
                  </Text>
                  <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.400')}>
                    Last Updated: {new Date().toLocaleString()}
                  </Text>
                </HStack>
                
                <Box p={4} bg={useColorModeValue('blue.50', 'blue.900')} borderRadius="md">
                  <Text fontSize="sm" color={useColorModeValue('blue.700', 'blue.200')}>
                    💡 <strong>Pro Tip:</strong> For real-time professional charts with advanced indicators, 
                    click the "TradingView" button above to view this stock on TradingView.
                  </Text>
                </Box>
              </VStack>
            </CardBody>
          </Card>
        </VStack>
      </Container>
    </Box>
  )
}
