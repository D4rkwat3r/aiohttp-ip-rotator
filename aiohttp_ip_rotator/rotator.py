from aiohttp import ClientSession
from aiohttp import ClientResponse
from random import choice
from random import randint
from struct import pack
from socket import inet_ntoa
from typing import Union
from typing import Optional
from aiobotocore.client import BaseClient
from botocore.exceptions import ClientError
from botocore.exceptions import EndpointConnectionError
from aioboto3.session import Session
from asyncio import sleep
from asyncio import gather
from asyncio import create_task
from uuid import uuid4


class RotatingClientSession(ClientSession):
    def __init__(
        self,
        target: str,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        host_header: Optional[str] = None,
        verbose: bool = False,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.target = target if not target.endswith("/") else target[:-1]
        if not target.startswith("http://") and not target.startswith("https://"):
            raise ValueError("Invalid URL schema")
        self.key_id = key_id
        self.key_secret = key_secret
        self.host_header = host_header or self.target.split("://", 1)[1].split("/", 1)[0]
        self.verbose = verbose
        self.endpoints = []
        self.name = f"IP Rotator for {self.target} ({str(uuid4())})"
        self.active = False
        self.regions = [
            "us-east-1", "us-east-2", "us-west-1", "us-west-2",
            "eu-west-1", "eu-west-2", "eu-west-3", "eu-north-1",
            "eu-central-1", "ca-central-1", "ap-south-1", "me-south-1"
            "ap-northeast-3", "ap-northeast-2", "ap-southeast-1",
            "ap-southeast-2", "ap-northeast-1", "sa-east-1",
            "ap-east-1", "af-south-1", "eu-south-1"
        ]

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args, **kwargs):
        await self.close()

    async def close(self):
        await self._clear_apis()
        await super().close()
        self.active = False

    def _print_if_verbose(self, message: str):
        if self.verbose: print(f">> {message}")

    async def _get_apis(self, region: str, client: BaseClient) -> list[dict]:
        position = None
        complete = False
        apis = []
        while not complete:
            try:
                gateways = await client.get_rest_apis(limit=500)\
                        if position is None \
                        else await client.get_rest_apis(limit=500, position=position)
            except (ClientError, EndpointConnectionError):
                self._print_if_verbose(f"Could not get list of APIs in region \"{region}\"")
                return []
            apis.extend(gateways["items"])
            position = gateways.get("position", None)
            if position is None:
                complete = True
        return apis

    async def _configure_api(self, client: BaseClient, api_id: str, api_resource_id: str, resource_id: str) -> None:
        await client.put_method(
            restApiId=api_id,
            resourceId=api_resource_id,
            httpMethod="ANY",
            authorizationType="NONE",
            requestParameters={
                "method.request.path.proxy": True,
                "method.request.header.X-Forwarded-Header": True,
                "method.request.header.X-Host": True
            }
        )
        await client.put_integration(
            restApiId=api_id,
            resourceId=api_resource_id,
            type="HTTP_PROXY",
            httpMethod="ANY",
            integrationHttpMethod="ANY",
            uri=self.target,
            connectionType="INTERNET",
            requestParameters={
                "integration.request.path.proxy": "method.request.path.proxy",
                "integration.request.header.X-Forwarded-For": "method.request.header.X-Forwarded-Header",
                "integration.request.header.Host": "method.request.header.X-Host"
            }
        )
        await client.put_method(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod="ANY",
            authorizationType="NONE",
            requestParameters={
                "method.request.path.proxy": True,
                "method.request.header.X-Forwarded-Header": True,
                "method.request.header.X-Host": True
            }
        )
        await client.put_integration(
            restApiId=api_id,
            resourceId=resource_id,
            type="HTTP_PROXY",
            httpMethod="ANY",
            integrationHttpMethod="ANY",
            uri=f"{self.target}/{{proxy}}",
            connectionType="INTERNET",
            requestParameters={
                "integration.request.path.proxy": "method.request.path.proxy",
                "integration.request.header.X-Forwarded-For": "method.request.header.X-Forwarded-Header",
                "integration.request.header.Host": "method.request.header.X-Host"
            }
        )
        await client.create_deployment(
            restApiId=api_id,
            stageName="proxy-stage"
        )

    async def _create_api(self, region: str) -> Optional[str]:
        async with Session().client(
                "apigateway",
                region_name=region,
                aws_access_key_id=self.key_id,
                aws_secret_access_key=self.key_secret
        ) as client:
            try:
                api_id = (await client.create_rest_api(name=self.name,
                                                       endpointConfiguration={"types": ["REGIONAL"]}))["id"]
            except (ClientError, EndpointConnectionError):
                self._print_if_verbose(f"Could not create new API in region \"{region}\"")
                return None
            api_resource_id = (await client.get_resources(restApiId=api_id))["items"][0]["id"]
            resource_id = (await client.create_resource(restApiId=api_id,
                                                        parentId=api_resource_id,
                                                        pathPart="{proxy+}"))["id"]
            await self._configure_api(client, api_id, api_resource_id, resource_id)
            self._print_if_verbose(f"Created API with id \"{api_id}\"")
            return f"{api_id}.execute-api.{region}.amazonaws.com"

    async def _clear_region_apis(self, region: str) -> None:
        async with Session().client(
                "apigateway",
                region_name=region,
                aws_access_key_id=self.key_id,
                aws_secret_access_key=self.key_secret
        ) as client:
            for api in await self._get_apis(region, client):
                if api["name"] == self.name:
                    try:
                        await client.delete_rest_api(restApiId=api["id"])
                    except ClientError as e:
                        if e.response["Error"]["Code"] == "TooManyRequestsException":
                            self._print_if_verbose("Too many requests when deleting rest API, sleeping for 3 seconds")
                            await sleep(3)
                            return await self._clear_region_apis(region)
                    self._print_if_verbose(f"Deleted rest API with id \"{api['id']}\"")

    async def _clear_apis(self) -> None:
        await gather(*[create_task(self._clear_region_apis(region)) for region in self.regions])
        self._print_if_verbose(f"All created APIs for ip rotating have been deleted")

    async def start(self) -> None:
        self._print_if_verbose(f"Starting IP Rotating APIs in {len(self.regions)} regions")
        endpoints = await gather(*[create_task(self._create_api(region)) for region in self.regions])
        self.endpoints.extend([endpoint for endpoint in endpoints if endpoint is not None])
        self._print_if_verbose(f"API launched in {len(self.endpoints)} regions out of {len(self.regions)}")
        self.active = True

    async def request(self, method: str, url: str, **kwargs) -> ClientResponse:
        if len(self.endpoints) == 0:
            raise RuntimeError("To send requests using the RotatingClientSession class, "
                               "first call [your RotatingClientSession instance].start() "
                               "or use async with RotatingClientSession(...) as session:")
        if not url.startswith("http://") and not url.startswith("https://"):
            raise ValueError("Invalid URL schema")
        endpoint = choice(self.endpoints)
        try: path = url.split("://", 1)[1].split("/", 1)[1]
        except IndexError: path = ""
        url = f"https://{endpoint}/proxy-stage/{path}"
        headers = kwargs.get("headers") or dict()
        if not isinstance(headers, dict):
            raise ValueError("Headers must be a dictionary-like object")
        headers.pop("X-Forwarded-For", None)
        kwargs.pop("headers", None)
        headers["X-Host"] = self.host_header
        headers["X-Forwarded-Header"] = headers.get("X-Forwarded-For") or inet_ntoa(pack(">I", randint(1, 0xffffffff)))
        return await super().request(method, url, headers=headers, **kwargs)

    async def get(self, url: str, *, allow_redirects: bool = True, **kwargs) -> ClientResponse:
        return await self.request("GET", url, allow_redirects=allow_redirects, **kwargs)

    async def options(self, url: str, *, allow_redirects: bool = True, **kwargs) -> ClientResponse:
        return await self.request("OPTIONS", url, allow_redirects=allow_redirects, **kwargs)

    async def head(self, url: str, *, allow_redirects: bool = False, **kwargs) -> ClientResponse:
        return await self.request("HEAD", url, allow_redirects=allow_redirects, **kwargs)

    async def post(self, url: str, *, data: Union[str, bytes, None] = None, **kwargs) -> ClientResponse:
        return await self.request("POST", url, data=data, **kwargs)

    async def put(self, url: str, *, data: Union[str, bytes, None] = None, **kwargs) -> ClientResponse:
        return await self.request("PUT", url, data=data, **kwargs)

    async def patch(self, url: str, *, data: Union[str, bytes, None] = None, **kwargs) -> ClientResponse:
        return await self.request("PATCH", url, data=data, **kwargs)

    async def delete(self, url: str, **kwargs) -> ClientResponse:
        return await self.request("DELETE", url, **kwargs)
