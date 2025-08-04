import { useState, useEffect } from 'react'
import {
  Box,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  TableCaption,
  useToast,
  IconButton,
  HStack,
  Text,
  Container,
  Heading
} from '@chakra-ui/react'
import { ChevronUpIcon, ChevronDownIcon } from '@chakra-ui/icons'
import axios from 'axios'

export default function PortfolioTable() {
  const [portfolioData, setPortfolioData] = useState([])
  const [filteredData, setFilteredData] = useState([])
  const [summaryData, setSummaryData] = useState(null)
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' })
  const [error, setError] = useState(null)
  const toast = useToast()

  useEffect(() => {
    const fetchPortfolioData = async () => {
      try {
        const response = await axios.get('http://localhost:5000/api/portfolio-with-live-prices')
        setPortfolioData(response.data.portfolioData)
      } catch (err) {
        setError('Failed to fetch portfolio data')
        console.error('Error fetching portfolio data:', err)
        toast({
          title: 'Error',
          description: 'Failed to fetch portfolio data. Please try again later.',
          status: 'error',
          duration: 5000,
          isClosable: true,
        })
      }
    }
    
    fetchPortfolioData()
    // Auto-refresh every 90 seconds
    const interval = setInterval(fetchPortfolioData, 90000)
    return () => clearInterval(interval)
  }, [toast])

  if (error) {
    return <Box padding='6' margin='50px'>Error: {error}</Box>
  }

  return (
    <Box overflowX='auto' padding='6'>
      <Table variant='striped' colorScheme='brand'>
        <TableCaption placement='top'>Portfolio Details</TableCaption>
        <Thead>
          <Tr>
            <Th>Stock Name</Th>
            <Th>Symbol</Th>
            <Th isNumeric>Quantity</Th>
            <Th isNumeric>Avg Buy Price</Th>
            <Th isNumeric>Current Price</Th>
            <Th isNumeric>Invested Value</Th>
            <Th isNumeric>Current Value</Th>
            <Th isNumeric>P&L</Th>
            <Th isNumeric>P&L %</Th>
          </Tr>
        </Thead>
        <Tbody>
          {portfolioData.map((stock, index) => (
            <Tr key={index}>
              <Td>{stock.stockName}</Td>
              <Td>{stock.symbol}</Td>
              <Td isNumeric>{stock.quantity}</Td>
              <Td isNumeric>₹{stock.avgBuyPrice}</Td>
              <Td isNumeric>₹{stock.currentPrice}</Td>
              <Td isNumeric>₹{stock.investedValue}</Td>
              <Td isNumeric>₹{stock.currentValue}</Td>
              <Td isNumeric color={stock.pnl >= 0 ? 'profit.500' : 'loss.500'}>
                ₹{stock.pnl}
              </Td>
              <Td isNumeric color={stock.pnlPercent >= 0 ? 'profit.500' : 'loss.500'}>
                {stock.pnlPercent}%
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Box>
  )
}
