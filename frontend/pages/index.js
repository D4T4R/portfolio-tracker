import { useState, useEffect } from 'react'
import {
  Box,
  Container,
  Heading,
  SimpleGrid,
  Spinner,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Button,
  Flex,
  Text,
  useToast,
  VStack,
  HStack
} from '@chakra-ui/react'
import Link from 'next/link'
import axios from 'axios'
import StockCard from '../components/StockCard'
import Portfolio from '../components/Portfolio'
import Navigation from '../components/Navigation'

export default function Home() {
  const [stockData, setStockData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError] = useState(null)
  const toast = useToast()

  const fetchStockData = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await axios.get('http://localhost:5000/api/prices')
      setStockData(response.data)
      setLastUpdated(new Date())
      
      if (lastUpdated) {
        toast({
          title: 'Data Updated',
          description: 'Stock prices have been refreshed',
          status: 'success',
          duration: 2000,
          isClosable: true,
        })
      }
    } catch (err) {
      setError('Failed to fetch stock data. Make sure the Flask backend is running on port 5000.')
      console.error('Error fetching stock data:', err)
      toast({
        title: 'Error',
        description: 'Failed to fetch stock data',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStockData()
    // Auto-refresh every 90 seconds
    const interval = setInterval(fetchStockData, 90000)
    return () => clearInterval(interval)
  }, [])

  if (loading && !stockData) {
    return (
      <Box minH="100vh" bg="gray.900">
        <Navigation />
        <Container maxW="container.xl" py={8}>
          <VStack spacing={8}>
            <Heading size="2xl" color="white" textAlign="center">
              Portfolio Tracker
            </Heading>
            <Spinner size="xl" color="blue.500" thickness="4px" />
            <Text color="gray.400">Loading stock data...</Text>
          </VStack>
        </Container>
      </Box>
    )
  }

  if (error) {
    return (
      <Box minH="100vh" bg="gray.900">
        <Navigation />
        <Container maxW="container.xl" py={8}>
          <VStack spacing={6}>
            <Heading size="2xl" color="white" textAlign="center">
              Portfolio Tracker
            </Heading>
            <Alert status="error" borderRadius="lg" maxW="md">
              <AlertIcon />
              <Box>
                <AlertTitle>Connection Error!</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Box>
            </Alert>
            <Button
              onClick={fetchStockData}
              colorScheme="blue"
              isLoading={loading}
              loadingText="Retrying..."
            >
              Retry
            </Button>
          </VStack>
        </Container>
      </Box>
    )
  }

  return (
    <Box minH="100vh" bg="gray.900">
      <Navigation />
      <Container maxW="container.xl" py={6}>
        <VStack spacing={6}>
          {/* Header */}
          <Flex 
            w="full" 
            justify="space-between" 
            align="center" 
            flexWrap="wrap" 
            gap={4}
          >
            <VStack align="start" spacing={1}>
              <Heading size="2xl" color="white">
                Live Portfolio Tracker
              </Heading>
              <Text color="gray.400" fontSize="sm">
                Real-time stock prices
                {lastUpdated && ` - Updated: ${lastUpdated.toLocaleTimeString()}`}
              </Text>
            </VStack>
            
            <HStack spacing={3}>
              <Link href="/portfolio" legacyBehavior passHref>
                <Button 
                  as="a"
                  colorScheme="purple" 
                  variant="outline"
                >
                  Portfolio Table
                </Button>
              </Link>
              <Button
                onClick={fetchStockData}
                colorScheme="blue"
                isLoading={loading}
                loadingText="Refreshing..."
              >
                Refresh
              </Button>
            </HStack>
          </Flex>

          {/* Main Content */}
          {stockData && (
            <>
              <Portfolio stockData={stockData} />
              <SimpleGrid columns={{ base: 1, md: 2, lg: 3, xl: 4 }} spacing={6} w="full">
                {Object.entries(stockData.prices).map(([name, data]) => (
                  <StockCard key={name} name={name} data={data} />
                ))}
              </SimpleGrid>
            </>
          )}
        </VStack>
      </Container>
    </Box>
  )
}
